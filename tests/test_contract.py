"""Tests for the frontend JSON contract (src/raceiq/ui/contract.py)."""

import json

import pytest

from raceiq.ui.contract import scenario_to_frontend
from raceiq.ui.scenario import build_scenario


@pytest.fixture
def normal_payload():
    # focus_gap brings the Haas car inside the Detection Gap so the bet is live
    return scenario_to_frontend(build_scenario(trap=False, seed=7, focus_gap=0.7))


@pytest.fixture
def trap_payload():
    return scenario_to_frontend(build_scenario(trap=True, seed=7, focus_gap=0.7))


def test_top_level_keys(normal_payload):
    assert set(normal_payload) == {
        "meta", "tower", "ego_row", "rival_row", "belief", "decision",
        "posture", "compliance", "compliance_rows", "frontier", "comparison",
        "soc_history", "speed_trace", "grid", "working", "provenance",
    }


def test_json_roundtrips(normal_payload):
    # Must be serialisable directly with no numpy/pandas objects left behind.
    text = json.dumps(normal_payload)
    again = json.loads(text)
    assert again["meta"]["ego"] == normal_payload["meta"]["ego"]


def test_tower_has_22_rows(normal_payload):
    assert len(normal_payload["tower"]) == 22
    row0 = normal_payload["tower"][0]
    assert set(row0) == {
        "position", "position_provenance", "driver", "team", "colour",
        "interval_s", "lap_delta_s", "est_soc_mj", "soc_provenance",
        "est_soc_pct", "mode", "mode_provenance",
    }


def test_normal_is_go_attack(normal_payload):
    assert normal_payload["decision"]["go"] == "GO"
    assert normal_payload["decision"]["recommendation"] == "ATTACK"
    assert normal_payload["decision"]["trap_flag"] is False


def test_trap_flips_to_hold(trap_payload):
    assert trap_payload["decision"]["trap_flag"] is True
    assert trap_payload["decision"]["go"] == "HOLD"
    assert trap_payload["decision"]["recommendation"] == "HOLD"


def test_belief_shape(normal_payload):
    b = normal_payload["belief"]
    assert len(b["probs"]) == 8
    assert set(b["p_ers"]) == {"H", "M", "Lharvest", "Lderate"}
    assert 0.0 <= b["p_overtake_available"] <= 1.0


def test_comparison_names_raceiq(trap_payload):
    comp = trap_payload["comparison"]
    assert comp["best_strategy"] == "RaceIQ"
    assert {"Greedy", "Conservative", "RaceIQ"} <= set(comp["by_total_time"])


def test_frames_are_plain_arrays(normal_payload):
    sh = normal_payload["soc_history"]
    assert isinstance(sh["lap"], list) and all(isinstance(x, float) for x in sh["lap"])
    st = normal_payload["speed_trace"]
    assert "clipping" in st and isinstance(st["clipping"][0], bool)


def test_meta_names_our_team_and_cars(normal_payload):
    m = normal_payload["meta"]
    assert m["our_team"] == "Haas F1 Team"
    assert m["focus"] in ("OCO", "BEA")
    assert m["teammate"] in ("OCO", "BEA")
    assert set(m["our_cars"]) == {"OCO", "BEA"}


def test_grid_rows_are_complete_and_ordered(normal_payload):
    g = normal_payload["grid"]
    assert len(g) == 22
    assert [r["position"] for r in g] == list(range(1, 23))
    assert sum(1 for r in g if r["is_ours"]) == 2


def test_working_shows_the_calculation(normal_payload):
    w = normal_payload["working"]
    assert len(w["chain"]) == 6
    t = w["ev_terms"]
    # the displayed EV must reconcile with the displayed terms
    assert abs(
        t["ev"] - (t["p_pass"] * t["points_gain"]
                   - t["repass_cost_pts"] - t["repayment_pts"]
                   - t["illegal_penalty"])
    ) < 1e-3
    assert set(w["eligibility"]) == {"gap_s", "detection_gap_s", "eligible"}
    assert "trap_test" in w and "price_of_energy" in w
    assert "compliance_measured" in w and "battery_estimate" in w


def test_real_grid_is_flagged_unedited():
    p = scenario_to_frontend(build_scenario(event="Monza", seed=7))
    assert p["meta"]["grid_edited"] is False
    assert p["meta"]["data_status"] == "cached_2026"


def test_baku_is_flagged_as_simulation():
    p = scenario_to_frontend(build_scenario(event="Baku", seed=7))
    assert p["meta"]["simulation_only"] is True
    assert p["meta"]["data_status"] == "not_raced_yet_2026"
