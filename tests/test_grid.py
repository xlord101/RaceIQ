"""Tests for the real 2026 grid registry (src/raceiq/ui/grid.py)."""

import pytest

from raceiq.ui.grid import (
    CANONICAL_LINEUP,
    DEMO_CIRCUITS,
    OUR_DRIVERS,
    OUR_TEAM,
    apply_edits,
    build_grid,
    circuit_status,
    load_lineup,
    our_cars,
)


def test_canonical_lineup_is_a_full_2026_field():
    assert len(CANONICAL_LINEUP) == 22
    codes = [c for c, *_ in CANONICAL_LINEUP]
    assert len(set(codes)) == 22, "no duplicate driver codes"
    assert set(OUR_DRIVERS) <= set(codes)


def test_haas_has_exactly_two_cars():
    haas = [c for c, _n, t, _col, _num in CANONICAL_LINEUP if t == OUR_TEAM]
    assert sorted(haas) == sorted(OUR_DRIVERS)
    assert OUR_TEAM == "Haas F1 Team"


@pytest.mark.parametrize("circuit", DEMO_CIRCUITS)
def test_build_grid_is_complete_and_ordered(circuit):
    g = build_grid(circuit, lap=34)
    assert len(g) == 22
    assert [r.position for r in g.rows] == list(range(1, 23))
    # intervals to the leader must be monotonic by construction
    intervals = [r.interval_s for r in g.rows]
    assert intervals == sorted(intervals)
    assert intervals[0] == 0.0


@pytest.mark.parametrize("circuit", DEMO_CIRCUITS)
def test_every_grid_has_both_haas_cars(circuit):
    g = build_grid(circuit, lap=34)
    cars = our_cars(g)
    assert len(cars) == 2
    assert {c.code for c in cars} == set(OUR_DRIVERS)
    assert all(c.is_ours for c in cars)


def test_real_telemetry_circuits_have_real_pace():
    """Melbourne / Shanghai / Monza were cached, so pace must be measured."""
    for circuit in ("Melbourne", "Shanghai", "Monza"):
        g = build_grid(circuit, lap=34)
        assert g.source == "fastf1_cache", circuit
        assert g.data_status == "cached_2026", circuit
        assert all(r.pace_s > 0 for r in g.rows), circuit
        # a plausible F1 lap, not a placeholder
        assert all(60.0 < r.pace_s < 200.0 for r in g.rows), circuit


def test_bahrain_and_baku_fall_back_and_are_flagged():
    for circuit, status in (("Bahrain", "no_fastf1_telemetry"),
                            ("Baku", "not_raced_yet_2026")):
        g = build_grid(circuit, lap=34)
        assert g.source == "canonical_lineup", circuit
        assert g.data_status == status, circuit
        assert len(g) == 22
    assert build_grid("Baku", lap=34).simulation_only is True


def test_fallback_order_is_not_alphabetical():
    """An alphabetical grid would be meaningless - guard against regression."""
    g = build_grid("Baku", lap=34)
    order = g.order
    assert order != sorted(order), "fallback must not be alphabetical"
    assert order[0] == "VER"


def test_fallback_gaps_are_realistic():
    """A 22-car field separated by 0.15 s each is not a race."""
    g = build_grid("Bahrain", lap=34)
    gaps = [r.gap_ahead_s for r in g.rows[1:]]
    assert all(0.3 <= x <= 1.5 for x in gaps), gaps
    assert g.rows[-1].interval_s > 8.0, "field must be spread out"


def test_car_ahead_and_row_lookup():
    g = build_grid("Melbourne", lap=34)
    assert g.row("VER") is not None
    assert g.row("XXX") is None
    p2 = g.rows[1]
    assert g.car_ahead(p2.code).code == g.rows[0].code
    assert g.car_ahead(g.rows[0].code) is None


def test_apply_edits_reorders_and_flags():
    g = build_grid("Melbourne", lap=34)
    assert g.edited is False
    e = apply_edits(g, order=["OCO", "BEA"] + [c for c in g.order
                                               if c not in ("OCO", "BEA")])
    assert e.edited is True
    assert e.order[0] == "OCO" and e.order[1] == "BEA"
    assert [r.position for r in e.rows] == list(range(1, 23))
    # the original grid must be untouched
    assert g.edited is False


def test_apply_edits_gap_override():
    g = build_grid("Monza", lap=34)
    code = g.rows[5].code
    e = apply_edits(g, gap_overrides={code: 0.6})
    assert e.row(code).gap_ahead_s == 0.6
    assert e.edited is True


def test_load_lineup_returns_real_teams():
    drivers, source = load_lineup("Monza")
    assert source == "fastf1_cache"
    assert len(drivers) == 22
    assert all(d.colour.startswith("#") for d in drivers)
    assert {d.team for d in drivers if d.code in OUR_DRIVERS} == {OUR_TEAM}


def test_circuit_status_reads_config():
    status, sim = circuit_status("Baku")
    assert status == "not_raced_yet_2026"
    assert sim is True


def test_demo_circuits_match_the_five_tracked_events():
    assert set(DEMO_CIRCUITS) == {"Melbourne", "Shanghai", "Monza", "Bahrain", "Baku"}
