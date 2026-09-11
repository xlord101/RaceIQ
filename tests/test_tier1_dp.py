"""Phase 4 tests: Tier-1 DP and the Pareto frontier.

Acceptance criteria from the spec: DP solves in <10 ms, the frontier is
monotonic in energy, and every action the DP can pick is FIA-legal.
"""

from __future__ import annotations

import time
from typing import List

import numpy as np
import pytest

from raceiq.config import RulesConfig, power_to_propel_kw
from raceiq.optimize.frontier import ParetoFrontier
from raceiq.optimize.tier1_dp import (
    Tier1DP,
    phase_durations,
    precompile,
    segment_actions,
    solve_lap_dp,
    solve_lap_dp_full,
)
from raceiq.track.segmentation import max_legal_deploy_kw
from raceiq.types import Segment

from conftest import needs_cache


# --------------------------------------------------------------------------
# Frontier (runs without any cached data)
# --------------------------------------------------------------------------

def test_frontier_is_monotonic_and_dominance_filtered():
    e = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    t = np.array([10.0, 9.0, 8.5, 8.6, 8.0])   # 3.0 MJ is dominated by 2.0
    f = ParetoFrontier(e, t)
    assert f.is_monotonic()
    # dominated point dropped, monotone hull kept
    assert np.all(np.diff(f.lap_time_s) <= 1e-12)
    assert 3.0 not in f.energy_mj


def test_frontier_lookup_roundtrip():
    e = np.linspace(0, 4, 9)
    t = 90.0 - 0.5 * e
    f = ParetoFrontier(e, t)
    assert f.time_for_energy(2.0) == pytest.approx(89.0, abs=1e-9)
    assert f.energy_for_time(89.0) == pytest.approx(2.0, abs=1e-9)
    assert f.exchange_rate() == pytest.approx(0.5, abs=1e-9)
    assert f.best_time_s == pytest.approx(88.0)
    assert f.baseline_time_s == pytest.approx(90.0)


# --------------------------------------------------------------------------
# Action legality (the DP may never see an illegal power)
# --------------------------------------------------------------------------

def test_every_action_is_legal(synthetic_segments, rules):
    horizons = phase_durations(synthetic_segments)
    for i, seg in enumerate(synthetic_segments):
        cap = max_legal_deploy_kw(seg.mean_speed_kph, seg, rules)
        powers, energies, times = segment_actions(seg, rules, float(horizons[i]))
        assert len(powers) == len(energies) == len(times)
        for p, e, dt in zip(powers, energies, times):
            if e > 0:                                   # deployment
                assert 0.0 < p <= cap + 1e-6, (seg.index, p, cap)
                assert p <= rules.mgu_k_max_kw + 1e-6
                assert p <= power_to_propel_kw(seg.mean_speed_kph, rules) + 1e-6
                assert dt < 0.0                         # deployment only helps
            else:
                assert dt >= 0.0                        # harvesting never helps


def test_coast_is_always_available(synthetic_segments, rules):
    """A car in a braking zone with a full battery must still have a legal move.

    Regression: before this, braking segments offered only 'harvest', so a full
    battery had no legal action and every DP state died.
    """
    horizons = phase_durations(synthetic_segments)
    for i, seg in enumerate(synthetic_segments):
        powers, energies, _ = segment_actions(seg, rules, float(horizons[i]))
        assert (np.asarray(energies) == 0.0).any(), f"segment {seg.index} has no coast"
        assert 0.0 in np.asarray(powers)


def test_no_deployment_under_braking(synthetic_segments, rules):
    horizons = phase_durations(synthetic_segments)
    for i, seg in enumerate(synthetic_segments):
        if seg.kind != "brake":
            continue
        powers, energies, _ = segment_actions(seg, rules, float(horizons[i]))
        assert not (np.asarray(energies) > 0).any(), "deploying under braking"


def test_phase_durations_break_at_braking(synthetic_segments):
    hor = phase_durations(synthetic_segments)
    assert len(hor) == len(synthetic_segments)
    assert np.all(hor > 0)
    # a braking zone starts a new phase, so its horizon is its own run
    for i in range(1, len(synthetic_segments)):
        prev, cur = synthetic_segments[i - 1], synthetic_segments[i]
        if (prev.kind == "brake") != (cur.kind == "brake"):
            assert hor[i] != hor[i - 1] or prev.length_m == cur.length_m


# --------------------------------------------------------------------------
# Solver invariants
# --------------------------------------------------------------------------

def test_dp_frontier_monotonic_and_bounded(synthetic_segments, rules):
    sol = solve_lap_dp_full(synthetic_segments, rules)
    f = sol.frontier
    assert len(f) >= 2
    assert f.is_monotonic()
    assert f.energy_mj[0] == pytest.approx(0.0, abs=1e-9)
    assert f.energy_mj[-1] <= rules.soc_window_mj + 1e-9
    # more energy never buys a slower lap
    assert f.lap_time_s[-1] < f.lap_time_s[0]
    assert sol.exchange_rate_s_per_mj > 0.0


def test_dp_respects_start_soc(synthetic_segments, rules):
    """A emptier battery at the start must cap the spendable energy."""
    full = solve_lap_dp_full(synthetic_segments, rules, start_soc_frac=1.0)
    half = solve_lap_dp_full(synthetic_segments, rules, start_soc_frac=0.5)
    assert half.frontier.max_energy_mj <= full.frontier.max_energy_mj + 1e-9
    assert half.frontier.max_energy_mj <= 0.5 * rules.soc_window_mj + 0.2


def test_dp_deterministic(synthetic_segments, rules):
    a = solve_lap_dp(synthetic_segments, rules)
    b = solve_lap_dp(synthetic_segments, rules)
    assert np.allclose(a.energy_mj, b.energy_mj)
    assert np.allclose(a.lap_time_s, b.lap_time_s)


def test_dp_soc_stays_inside_window(synthetic_segments, rules):
    """No reachable end state may sit outside the usable window."""
    sol = solve_lap_dp_full(synthetic_segments, rules)
    assert np.all(sol.frontier.energy_mj >= -1e-9)
    assert np.all(sol.frontier.energy_mj <= rules.soc_window_mj + 1e-9)


def test_dp_solve_under_10ms(synthetic_segments, rules):
    """Spec: Tier-1 DP runs in single-digit milliseconds."""
    prog = precompile(synthetic_segments, rules)
    solve_lap_dp(synthetic_segments, rules, program=prog)          # warm up
    times = []
    for _ in range(7):
        t0 = time.perf_counter()
        solve_lap_dp(synthetic_segments, rules, program=prog)
        times.append((time.perf_counter() - t0) * 1000.0)
    assert min(times) < 10.0, f"best {min(times):.2f} ms"
    assert sorted(times)[len(times) // 2] < 10.0, f"median {sorted(times)[3]:.2f} ms"


def test_tier1dp_caches_and_reuses_program(synthetic_segments, rules):
    dp = Tier1DP(rules, synthetic_segments)
    first = dp.solve()
    assert first.solve_ms > 0.0 or len(dp.program.stages) > 0
    assert dp.frontier.is_monotonic()
    cached = dp.solve()
    assert cached is first                       # not re-solved
    assert dp.exchange_rate() > 0.0


def test_recovered_plan_is_legal(synthetic_segments, rules):
    dp = Tier1DP(rules, synthetic_segments)
    plan = dp.plan()
    assert len(plan) == len(synthetic_segments)
    for seg, p in zip(synthetic_segments, plan):
        if np.isnan(p) or p <= 0:
            continue
        assert p <= max_legal_deploy_kw(seg.mean_speed_kph, seg, rules) + 1e-6


def test_frontier_point_count_honours_soc_bins(synthetic_segments, rules):
    n = 12
    f = solve_lap_dp(synthetic_segments, rules, soc_bins=n)
    assert len(f) <= n


# --------------------------------------------------------------------------
# Real cached telemetry
# --------------------------------------------------------------------------

@needs_cache
def test_dp_on_real_circuit(real_segments, rules):
    assert real_segments, "no cached segments"
    sol = solve_lap_dp_full(real_segments, rules)
    assert len(sol.frontier) >= 5
    assert sol.frontier.is_monotonic()
    assert 0.0 < sol.exchange_rate_s_per_mj < 5.0
    # spending the whole window must be worth a plausible amount of lap time
    gain = sol.frontier.lap_time_s[0] - sol.frontier.lap_time_s[-1]
    assert 0.2 < gain < 6.0, f"implausible lap-time gain {gain:.2f} s"


@needs_cache
def test_dp_under_10ms_on_real_circuit(real_segments, rules):
    prog = precompile(real_segments, rules)
    solve_lap_dp(real_segments, rules, program=prog)
    times = []
    for _ in range(7):
        t0 = time.perf_counter()
        solve_lap_dp(real_segments, rules, program=prog)
        times.append((time.perf_counter() - t0) * 1000.0)
    assert sorted(times)[len(times) // 2] < 10.0, f"median {sorted(times)[3]:.2f} ms"


@needs_cache
def test_exchange_rate_orders_circuits_by_drag(rules, cached_events):
    """Monza (low drag, terminal velocity) must value energy less than Melbourne."""
    if not {"Melbourne", "Monza"} <= set(cached_events):
        pytest.skip("needs both Melbourne and Monza cached")
    from raceiq.pipeline import build_replay

    rates = {}
    for ev in ("Melbourne", "Monza"):
        segs = build_replay(ev, 2026, "R", rules).segments
        rates[ev] = solve_lap_dp(segs, rules).exchange_rate()
    assert rates["Monza"] < rates["Melbourne"], rates
