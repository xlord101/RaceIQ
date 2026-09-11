"""Phase 7 tests: the Streamlit-facing scenario builder (`raceiq.ui.scenario`).

These tests deliberately do NOT depend on Streamlit. They lock down the *data*
contract the UI renders, so the app can be refactored freely as long as the
scenario keeps its shape and its semantics.
"""

from __future__ import annotations

import numpy as np
import pytest

from raceiq.ui.scenario import (
    DRIVER_GRID,
    TEAM_COLOURS,
    DriverRow,
    Scenario,
    build_scenario,
)


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------
def test_build_scenario_returns_full_contract():
    scn = build_scenario()
    assert isinstance(scn, Scenario)
    assert scn.event == "Melbourne"
    assert scn.lap == 34


def test_tower_is_twenty_two_rows():
    scn = build_scenario()
    assert len(scn.tower) == 22
    assert all(isinstance(r, DriverRow) for r in scn.tower)


def test_tower_positions_are_strictly_ordered():
    scn = build_scenario()
    positions = [r.position for r in scn.tower]
    assert positions == list(range(1, 23))


def test_intervals_are_monotonically_increasing():
    """A timing tower is cumulative: P2 can never be closer than P1."""
    scn = build_scenario()
    intervals = [r.interval_s for r in scn.tower]
    assert all(b >= a - 1e-9 for a, b in zip(intervals, intervals[1:]))
    assert intervals[0] == pytest.approx(0.0, abs=1e-9)


def test_estimated_soc_stays_inside_the_rules_window():
    scn = build_scenario()
    for row in scn.tower:
        assert 0.0 <= row.est_soc_mj <= scn.window_mj + 1e-9
        assert 0.0 <= row.est_soc_pct <= 100.0 + 1e-9


def test_ers_modes_are_drawn_from_known_postures():
    scn = build_scenario()
    known = {"Harvest", "Balance", "Deploy"}
    assert {r.mode for r in scn.tower} <= known


def test_grid_matches_2026_entry_list_size():
    assert len(DRIVER_GRID) == 22
    teams = {team for _, team in DRIVER_GRID}
    assert teams <= set(TEAM_COLOURS), "every team needs a colour"


def test_team_colours_are_hex():
    for colour in TEAM_COLOURS.values():
        assert colour.startswith("#") and len(colour) == 7


# --------------------------------------------------------------------------
# Determinism (spec: offline-first, reproducible demo)
# --------------------------------------------------------------------------
def test_build_scenario_is_deterministic():
    a = build_scenario(seed=7)
    b = build_scenario(seed=7)
    assert [r.est_soc_mj for r in a.tower] == pytest.approx(
        [r.est_soc_mj for r in b.tower]
    )
    assert a.decision.recommendation == b.decision.recommendation


def test_different_seeds_change_soc_but_not_contract():
    a = build_scenario(seed=1)
    b = build_scenario(seed=2)
    assert [r.est_soc_mj for r in a.tower] != pytest.approx(
        [r.est_soc_mj for r in b.tower]
    )
    assert len(a.tower) == len(b.tower) == 22


# --------------------------------------------------------------------------
# Belief / decision wiring
# --------------------------------------------------------------------------
def test_clean_rival_does_not_raise_the_trap_flag():
    scn = build_scenario(trap=False)
    assert scn.belief.trap_flag is False


def test_trap_flag_is_raised_when_rival_conserves_in_aero_zone():
    scn = build_scenario(trap=True)
    assert scn.belief.trap_flag is True


def test_trap_flips_the_recommendation_to_hold():
    """The headline demo: identical situation, rival's hidden intent changes the call."""
    # focus_gap brings our Haas car inside the Detection Gap so the bet is live;
    # on the untouched real grid Haas is several seconds back and no bet is made.
    clean = build_scenario(trap=False, focus_gap=0.7)
    trapped = build_scenario(trap=True, focus_gap=0.7)
    assert clean.decision.go == "GO"
    assert trapped.decision.go == "HOLD"
    assert trapped.decision.recommendation == "HOLD"


def test_trap_reduces_pass_probability():
    clean = build_scenario(trap=False)
    trapped = build_scenario(trap=True)
    assert trapped.decision.p_pass < clean.decision.p_pass


def test_trap_reduces_expected_value():
    clean = build_scenario(trap=False)
    trapped = build_scenario(trap=True)
    assert trapped.decision.ev < clean.decision.ev


def test_decision_exposes_a_human_readable_why_line():
    scn = build_scenario()
    why = str(scn.decision.why)
    assert len(why) > 10
    # no emojis anywhere in UI-facing strings (spec Section 3)
    assert all(ord(ch) < 0x1F000 for ch in why)


def test_ego_and_rival_are_distinct_drivers():
    scn = build_scenario()
    assert scn.ego != scn.rival
    assert scn.ego_row.driver == scn.ego
    assert scn.rival_row.driver == scn.rival


def test_rival_is_the_car_directly_ahead():
    """The bet is always priced against the car in front."""
    scn = build_scenario()
    assert scn.rival_row.position == scn.ego_row.position - 1


def test_real_grid_is_honest_and_focus_gap_makes_the_bet_live():
    """The real grid is never manipulated; editing it is what prices the bet."""
    real = build_scenario()
    assert real.grid is not None and real.grid.edited is False
    # If the real running order puts Haas outside the Detection Gap the tool
    # must say so rather than inventing a favourable gap.
    if real.gap_at_detection_s > real.detection_gap_s:
        assert real.eligible is False

    battle = build_scenario(focus_gap=0.7)
    assert battle.gap_at_detection_s <= battle.detection_gap_s
    assert battle.eligible is True
    assert battle.grid is not None and battle.grid.edited is True


def test_scenario_is_built_for_our_team_haas():
    """RaceIQ is the Haas pit wall: we advise a Haas car, not a generic P3."""
    scn = build_scenario()
    assert scn.our_team == "Haas F1 Team"
    assert scn.focus in ("OCO", "BEA")
    assert scn.ego == scn.focus
    assert scn.ego_row.team == "Haas F1 Team"
    assert scn.teammate in ("OCO", "BEA")
    assert scn.teammate != scn.focus


def test_top5_returns_five_names():
    scn = build_scenario()
    assert len(scn.top5) == 5
    assert scn.top5 == [r.driver for r in scn.tower[:5]]


# --------------------------------------------------------------------------
# Compliance board
# --------------------------------------------------------------------------
def test_compliance_board_has_nine_rules():
    scn = build_scenario()
    assert len(scn.compliance_rows) == 9


def test_compliance_rows_carry_rule_id_status_and_detail():
    scn = build_scenario()
    for row in scn.compliance_rows:
        assert "rule" in row
        assert row["status"] in {"PASS", "FAIL"}


def test_mpc_plan_is_rule_compliant():
    """The plan we show on the pit wall must actually be legal."""
    scn = build_scenario()
    assert scn.compliance.passed is True
    assert scn.compliance.violations == []


def test_posture_is_one_of_the_four_modes():
    scn = build_scenario()
    assert scn.posture.posture in {"ATTACK", "NEUTRAL", "HARVEST", "DEFEND"}


def test_posture_carries_a_horizon_and_alternatives():
    scn = build_scenario()
    assert scn.posture.horizon_laps >= 1
    assert set(scn.posture.alternatives) == {"ATTACK", "NEUTRAL", "HARVEST", "DEFEND"}


# --------------------------------------------------------------------------
# Circuits / parametrisation
# --------------------------------------------------------------------------
@pytest.mark.parametrize("event", ["Melbourne", "Bahrain", "Shanghai", "Monza", "Baku"])
def test_every_demo_circuit_builds(event):
    scn = build_scenario(event=event)
    assert scn.event == event
    assert len(scn.tower) == 22
    assert scn.compliance.passed is True


def test_harvest_potential_is_carried_through():
    scn = build_scenario(harvest_mj=7.1)
    assert scn.circuit_harvest_potential_mj == pytest.approx(7.1)


def test_high_harvest_circuit_is_at_least_as_aggressive_as_low():
    """Baku (7.1 MJ) should never recommend a more conservative posture than Monza (3.3)."""
    order = {"ATTACK": 0, "NEUTRAL": 1, "DEFEND": 2, "HARVEST": 3}
    baku = build_scenario(event="Baku", harvest_mj=7.1)
    monza = build_scenario(event="Monza", harvest_mj=3.3)
    assert order[baku.posture.posture] <= order[monza.posture.posture]


def test_ego_index_selects_the_row():
    scn = build_scenario(ego_index=5)
    assert scn.ego_row.position == 6


# --------------------------------------------------------------------------
# Charts data
# --------------------------------------------------------------------------
def test_soc_history_has_lap_column_plus_driver_series():
    scn = build_scenario()
    assert "lap" in scn.soc_history.columns
    assert len(scn.soc_history.columns) > 1
    assert scn.soc_history["lap"].is_monotonic_increasing


def test_soc_history_covers_many_laps():
    scn = build_scenario()
    assert len(scn.soc_history) >= 20
    assert scn.soc_history["lap"].min() >= 1


def test_soc_history_is_bounded_by_the_window():
    scn = build_scenario()
    drivers = [c for c in scn.soc_history.columns if c != "lap"]
    assert drivers, "expected at least one driver series"
    values = scn.soc_history[drivers].to_numpy()
    assert values.min() >= -1e-9
    assert values.max() <= scn.window_mj + 1e-9


def test_speed_trace_has_required_columns():
    scn = build_scenario()
    for col in ("Distance", "Speed", "clipping"):
        assert col in scn.speed_trace.columns


def test_speed_trace_is_physically_plausible():
    scn = build_scenario()
    s = scn.speed_trace["Speed"].to_numpy(dtype=float)
    assert s.min() > 40.0
    assert s.max() < 380.0
    assert np.all(np.diff(s) < 60.0), "no implausible instant acceleration"
    assert np.all(s > 0.0)


def test_speed_trace_clipping_flags_are_boolean():
    scn = build_scenario()
    assert set(np.unique(scn.speed_trace["clipping"].to_numpy())) <= {0, 1, False, True}


def test_speed_trace_distance_increases():
    scn = build_scenario()
    d = scn.speed_trace["Distance"].to_numpy(dtype=float)
    assert np.all(np.diff(d) > 0.0)


# --------------------------------------------------------------------------
# Baselines shown in the UI
# --------------------------------------------------------------------------
def test_comparison_includes_all_three_strategies():
    scn = build_scenario()
    assert set(scn.comparison.results) == {"RaceIQ", "Greedy", "Conservative"}


def test_raceiq_is_the_fastest_baseline():
    scn = build_scenario()
    assert scn.comparison.best_strategy == "RaceIQ"


def test_raceiq_beats_greedy():
    scn = build_scenario()
    raceiq = sum(scn.comparison.results["RaceIQ"].lap_time_s)
    greedy = sum(scn.comparison.results["Greedy"].lap_time_s)
    assert raceiq < greedy


# --------------------------------------------------------------------------
# Watermark (spec: SoC is always labelled Estimated)
# --------------------------------------------------------------------------
def test_watermark_is_present_and_mentions_estimate():
    scn = build_scenario()
    assert "Estimated" in scn.watermark
    assert "SoC" in scn.watermark


def test_no_emoji_anywhere_in_scenario_strings():
    scn = build_scenario()
    blob = " ".join(
        [scn.ego, scn.rival, scn.watermark, str(scn.decision.why)]
        + [r.driver for r in scn.tower]
        + [r.team for r in scn.tower]
    )
    assert all(ord(ch) < 0x1F000 for ch in blob)
