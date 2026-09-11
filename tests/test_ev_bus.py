"""Tests for the EV-bus transfer solver (Phase 9).

The bus solver is the F1 energy logic driven by a different config file. These
tests confirm it picks sensible drive modes and never recommends something that
would drop the bus below its mandated reserve.
"""

import numpy as np
import pytest

from raceiq.transfer import BUS_POSTURES, BusState, EVBusSolver
from raceiq.types import BusRecommendation


def _solver():
    return EVBusSolver()


def _state(**kw):
    base = dict(
        soc_pct=70.0,
        stops_remaining=10,
        distance_to_next_stop_m=800.0,
        schedule_slack_s=0.0,
        total_stops=20,
        payload_tonnes=0.0,
    )
    base.update(kw)
    return BusState(**base)


def test_recommend_returns_valid_recommendation():
    rec = _solver().recommend(_state())
    assert isinstance(rec, BusRecommendation)
    assert rec.mode in BUS_POSTURES
    assert 0.0 <= rec.projected_soc_pct <= 100.0
    assert 0.0 <= rec.power_fraction <= 1.0
    assert rec.reserve_soc_pct >= 0.0


def test_low_soc_triggers_charge_protection():
    sol = _solver()
    rec = sol.recommend(_state(soc_pct=10.0))
    # At/below the reserve band the solver must protect charge, never spend.
    assert rec.mode in ("HARVEST", "DEFEND")
    assert rec.mode not in ("ATTACK", "NEUTRAL")
    # The chosen mode must be at least as charge-protective as ATTACK.
    assert rec.projected_soc_pct >= sol.project_soc(_state(soc_pct=10.0), "ATTACK") - 1e-6


def test_recoverable_low_soc_is_feasible():
    # A low-but-recoverable start with few stops left can hold the reserve.
    rec = _solver().recommend(_state(soc_pct=22.0, stops_remaining=2))
    assert rec.feasible
    assert rec.projected_soc_pct >= rec.reserve_soc_pct - 0.5 - 1e-6


def test_behind_schedule_with_charge_attacks():
    rec = _solver().recommend(_state(soc_pct=80.0, schedule_slack_s=-45.0))
    assert rec.mode == "ATTACK"
    # Attacking must still be feasible (reserve protected).
    assert rec.feasible
    assert rec.projected_soc_pct >= rec.reserve_soc_pct - 0.5 - 1e-6


def test_comfortably_ahead_harvests():
    rec = _solver().recommend(_state(soc_pct=85.0, schedule_slack_s=120.0))
    assert rec.mode == "HARVEST"


def test_attack_recovers_schedule_faster_than_harvest():
    s = _state(soc_pct=80.0, schedule_slack_s=-30.0, stops_remaining=10)
    rec = _solver().recommend(s)
    # ATTACK must pull the schedule back (negative delta) vs HARVEST slipping.
    harvest = _solver().recommend(_state(soc_pct=85.0, schedule_slack_s=120.0))
    assert rec.schedule_delta_s < 0.0
    assert harvest.schedule_delta_s >= 0.0


def test_energy_saved_vs_attack_baseline_is_nonneg_for_harvest():
    # HARVEST must consume no more than the always-attack baseline.
    s = _state(soc_pct=70.0, schedule_slack_s=30.0)
    rec = _solver().recommend(s)
    if rec.mode in ("HARVEST", "DEFEND", "NEUTRAL"):
        assert rec.energy_saved_kwh >= -1e-9


def test_projected_soc_monotonic_in_charge():
    # More starting charge can only help the projected depot SoC (other fixed).
    s = _state(soc_pct=60.0, stops_remaining=8)
    more = _state(soc_pct=90.0, stops_remaining=8)
    sol = _solver()
    assert sol.project_soc(more, "NEUTRAL") >= sol.project_soc(s, "NEUTRAL") - 1e-6


def test_per_stop_plan_length_matches_stops():
    rec = _solver().recommend(_state(stops_remaining=7))
    assert rec.per_stop_plan is not None
    assert len(rec.per_stop_plan) == 7
    assert all("net_kwh" in d for d in rec.per_stop_plan)


def test_descent_adds_regen():
    sol = _solver()
    flat = _state(soc_pct=70.0, stops_remaining=10, is_descent=False)
    descent = _state(soc_pct=70.0, stops_remaining=10, is_descent=True)
    # A descent recovers more, so projected SoC is higher.
    assert sol.project_soc(descent, "NEUTRAL") >= sol.project_soc(flat, "NEUTRAL") - 1e-9


def test_recommend_is_deterministic():
    sol = _solver()
    a = sol.recommend(_state(soc_pct=55.0, schedule_slack_s=-10.0))
    b = sol.recommend(_state(soc_pct=55.0, schedule_slack_s=-10.0))
    assert a.mode == b.mode
    assert np.isclose(a.projected_soc_pct, b.projected_soc_pct)
