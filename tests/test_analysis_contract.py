"""Tests for Phase 18A Analysis Data Contract and Factual Exports."""

import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent

STATE_NAMES = [
    "H|OT_avail",
    "H|OT_spent",
    "M|OT_avail",
    "M|OT_spent",
    "Lharvest|OT_avail",
    "Lharvest|OT_spent",
    "Lderate|OT_avail",
    "Lderate|OT_spent",
]

CANONICAL_12_FEATURES = [
    "gap_ahead_s",
    "closing_speed_kph",
    "straight_remaining_m",
    "tyre_age_delta_laps",
    "own_est_soc",
    "rival_est_soc",
    "rival_P_Lderate",
    "rival_P_Lharvest",
    "trap_flag",
    "overtake_mode_active",
    "circuit_harvest_potential_mj",
    "laps_remaining",
]

EV_BREAKDOWN_FIELDS = [
    "p_pass",
    "points_gain",
    "repass_cost_pts",
    "repayment_cost_s",
    "repayment_cost_pts",
    "illegal_penalty",
    "strategic_ev",
    "recommendation",
    "repass_risk",
    "why",
]

CIRCUITS = ["Melbourne", "Shanghai", "Monza"]
DATA_DIRS = [
    ROOT / "lovable_extracted" / "src" / "data",
    ROOT / "frontend" / "src" / "data",
]


@pytest.mark.parametrize("circuit", CIRCUITS)
@pytest.mark.parametrize("data_dir", DATA_DIRS)
def test_factual_replay_metadata(circuit: str, data_dir: Path):
    file_path = data_dir / f"{circuit}_factual.json"
    assert file_path.exists(), f"File {file_path} missing"
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("metadata", {})
    assert meta.get("season") == 2026
    assert meta.get("sessionType") == "Race"
    assert meta.get("telemetryYear") == 2026
    assert meta.get("ruleset") == "2026"
    assert meta.get("positionsProvenance") == "ACTUAL"
    assert meta.get("energyProvenance") == "INFERRED"
    assert data.get("harvestCapMj") == 8.5
    assert len(data.get("laps", [])) > 0


@pytest.mark.parametrize("circuit", CIRCUITS)
@pytest.mark.parametrize("data_dir", DATA_DIRS)
def test_full_hmm_belief_exposure(circuit: str, data_dir: Path):
    file_path = data_dir / f"{circuit}_factual.json"
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    recs_found = 0
    for lap in data["laps"]:
        for d in lap["drivers"]:
            rec = d.get("recommendation")
            if rec and "hmm_belief" in rec:
                recs_found += 1
                hb = rec["hmm_belief"]
                prob_sum = sum(hb[name] for name in STATE_NAMES)
                assert abs(prob_sum - 1.0) < 0.005, f"HMM probs must sum to ~1.0, got {prob_sum}"
                assert 0.0 <= hb["p_ot_avail"] <= 1.0
                assert 0.0 <= hb["p_Lderate"] <= 1.0
                assert 0.0 <= hb["p_Lharvest"] <= 1.0
                assert isinstance(hb["trap_flag"], bool)
                assert 0.0 <= hb["trap_prob"] <= 1.0

    assert recs_found > 0, f"No recommendations with hmm_belief found in {file_path}"


@pytest.mark.parametrize("circuit", CIRCUITS)
@pytest.mark.parametrize("data_dir", DATA_DIRS)
def test_canonical_pass_model_features(circuit: str, data_dir: Path):
    file_path = data_dir / f"{circuit}_factual.json"
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for lap in data["laps"]:
        for d in lap["drivers"]:
            rec = d.get("recommendation")
            if rec and "pass_features" in rec:
                pf = rec["pass_features"]
                for f_name in CANONICAL_12_FEATURES:
                    assert f_name in pf, f"Missing feature {f_name} in {file_path}"
                assert pf["model_status"] == "HEURISTIC"
                assert 0.0 <= pf["p_pass"] <= 1.0


@pytest.mark.parametrize("circuit", CIRCUITS)
@pytest.mark.parametrize("data_dir", DATA_DIRS)
def test_ev_breakdown_exposure(circuit: str, data_dir: Path):
    file_path = data_dir / f"{circuit}_factual.json"
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for lap in data["laps"]:
        for d in lap["drivers"]:
            rec = d.get("recommendation")
            if rec and "ev_breakdown" in rec:
                ev_b = rec["ev_breakdown"]
                for f_name in EV_BREAKDOWN_FIELDS:
                    assert f_name in ev_b, f"Missing EV field {f_name} in {file_path}"
                assert ev_b["recommendation"] in ["ATTACK", "HOLD", "HARVEST", "DEFEND"]
                assert 0.0 <= ev_b["repass_risk"] <= 1.0


@pytest.mark.parametrize("circuit", CIRCUITS)
@pytest.mark.parametrize("data_dir", DATA_DIRS)
def test_sublap_checkpoints_integrity(circuit: str, data_dir: Path):
    file_path = data_dir / f"{circuit}_factual.json"
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    sublaps_found = 0
    for lap in data["laps"]:
        for d in lap["drivers"]:
            sub = d.get("subLap")
            if sub is not None:
                sublaps_found += 1
                assert len(sub["soc"]) == 16
                assert len(sub["modes"]) == 16
                assert len(sub["kinds"]) == 16
                assert len(sub["clips"]) == 16
                for s in sub["soc"]:
                    assert 0.05 <= s <= 0.98

    assert sublaps_found > 0, f"No subLap checkpoints found in {file_path}"
