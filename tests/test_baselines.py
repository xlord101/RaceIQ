"""Phase 8 tests: baseline comparison (RaceIQ vs Greedy vs Conservative)."""

import numpy as np
import pytest

from raceiq.baselines import (
    Comparison,
    ConservativeStrategy,
    GreedyStrategy,
    RaceIQStrategy,
    RaceSimulator,
    compare,
)
from raceiq.optimize import ParetoFrontier


def _frontier():
    energy = np.array([0.0, 2.0, 4.0, 6.0, 8.0])
    times = np.array([92.0, 90.5, 89.5, 89.0, 88.7])
    return ParetoFrontier(energy, times)


def test_greedy_attacks_more_than_conservative():
    sim = RaceSimulator(_frontier(), circuit_harvest_potential_mj=3.3)
    g = sim.simulate(GreedyStrategy(), laps=20, initial_soc_mj=2.5)
    c = sim.simulate(ConservativeStrategy(), laps=20, initial_soc_mj=2.5)
    assert g.attack_laps > c.attack_laps
    assert c.attack_laps == 0  # conservative never attacks


def test_conservative_preserves_more_soc():
    sim = RaceSimulator(_frontier(), circuit_harvest_potential_mj=3.3)
    g = sim.simulate(GreedyStrategy(), laps=20, initial_soc_mj=2.5)
    c = sim.simulate(ConservativeStrategy(), laps=20, initial_soc_mj=2.5)
    assert c.min_soc_mj > g.min_soc_mj


def test_raceiq_produces_valid_plan_each_lap():
    sim = RaceSimulator(_frontier(), circuit_harvest_potential_mj=5.0)
    r = sim.simulate(RaceIQStrategy(_frontier()), laps=15, initial_soc_mj=2.5)
    assert len(r.lap_time_s) == 15
    assert all(np.isfinite(r.lap_time_s))
    assert r.min_soc_mj >= 0.0


def test_compare_returns_all_three():
    comp = compare(
        _frontier(),
        laps=20,
        initial_soc_mj=2.5,
        circuit_harvest_potential_mj=3.3,
    )
    assert isinstance(comp, Comparison)
    assert set(comp.results.keys()) == {"Greedy", "Conservative", "RaceIQ"}
    assert comp.best_strategy in comp.results
    assert "RaceIQ" in comp.by_total_time


def test_compare_table_rows():
    comp = compare(_frontier(), laps=10, circuit_harvest_potential_mj=3.3)
    rows = comp.as_rows()
    assert len(rows) == 3
    for row in rows:
        assert "strategy" in row and "total_time_s" in row


def test_low_harvest_circuit_runs():
    # Monza-like low harvest must not crash the comparison.
    comp = compare(_frontier(), laps=15, circuit_harvest_potential_mj=3.3)
    assert "RaceIQ" in comp.results
    # Baku-like high harvest must not crash either.
    comp2 = compare(_frontier(), laps=15, circuit_harvest_potential_mj=7.1)
    assert "RaceIQ" in comp2.results


def test_raceiq_beats_baselines_in_pack():
    """In a pack (repeatedly within the Detection Gap) RaceIQ wins on time:
    Greedy over-attacks and depletes; Conservative is too slow."""
    sim = RaceSimulator(
        _frontier(),
        circuit_harvest_potential_mj=3.3,
        rival_pace_s=89.4,
        pack_reset_gap_s=2.0,
    )
    g = sim.simulate(GreedyStrategy(), laps=20, initial_soc_mj=2.5)
    c = sim.simulate(ConservativeStrategy(), laps=20, initial_soc_mj=2.5)
    r = sim.simulate(RaceIQStrategy(_frontier()), laps=20, initial_soc_mj=2.5)
    assert r.total_time_s <= g.total_time_s
    assert r.total_time_s <= c.total_time_s
    # Greedy's over-attacking must cost it battery health vs RaceIQ.
    assert g.min_soc_mj <= r.min_soc_mj
