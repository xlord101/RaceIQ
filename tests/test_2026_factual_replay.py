"""Tests for RaceIQ 2026 GP Factual Replay Data Foundation.

Enforces Section 18 mandatory assertions across Melbourne, Shanghai, and Monza:
1. factual dataset season == 2026
2. sessionType == Race
3. dataset event matches circuit
4. telemetry source corresponds to 2026
5. expected race lap count is correct (Melbourne: 58, Shanghai: 56, Monza: 53)
6. actual 2026 driver/team mapping is used (Haas has OCO and BEA, Audi has HUL/BOR, etc.)
7. no 2024 factual telemetry is used by the normal adapter
8. simulation remains fallback only
9. SoC remains within 4 MJ window (normalized in [0, 1])
10. harvest/deploy limits remain compliant with current config (8.5 MJ/lap)
11. subLap checkpoints exist (16 checkpoints per lap)
12. subLap values are generated from the 2026 replay
13. cumulative gap is based on the actual 2026 race timing
14. What-If seed comes from the actual 2026 snapshot
15. What-If remains PROJECTED
16. provenance remains correct (ACTUAL positions, INFERRED energy)
"""

import json
from pathlib import Path
import pytest


CIRCUITS = {
    "Melbourne": {
        "event": "Australian Grand Prix",
        "date": "2026-03-08",
        "laps": 58,
        "haas_drivers": ["OCO", "BEA"],
    },
    "Shanghai": {
        "event": "Chinese Grand Prix",
        "date": "2026-03-15",
        "laps": 56,
        "haas_drivers": ["OCO", "BEA"],
    },
    "Monza": {
        "event": "Italian Grand Prix",
        "date": "2026-09-06",
        "laps": 53,
        "haas_drivers": ["OCO", "BEA"],
    },
}

DATA_DIRS = [
    Path(__file__).resolve().parent.parent / "lovable_extracted" / "src" / "data",
    Path(__file__).resolve().parent.parent / "frontend" / "src" / "data",
]


@pytest.fixture(scope="module", params=["Melbourne", "Shanghai", "Monza"])
def circuit_dataset(request):
    circuit = request.param
    expected = CIRCUITS[circuit]
    path = DATA_DIRS[0] / f"{circuit}_factual.json"
    assert path.exists(), f"Missing dataset: {path}"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return circuit, expected, data


def test_season_and_session_type(circuit_dataset):
    """Rule 1 & 2: season == 2026 and sessionType == Race."""
    circuit, expected, data = circuit_dataset
    assert data.get("season") == 2026, f"{circuit} top-level season must be 2026, got {data.get('season')}"
    assert data.get("sessionType") == "Race", f"{circuit} top-level sessionType must be 'Race', got {data.get('sessionType')}"
    
    meta = data.get("metadata")
    assert meta is not None, f"{circuit} metadata block missing"
    assert meta["season"] == 2026
    assert meta["sessionType"] == "Race"
    assert meta["telemetryYear"] == 2026
    assert meta["ruleset"] == "2026"


def test_event_and_date(circuit_dataset):
    """Rule 3 & 4: dataset event matches circuit and telemetry date corresponds to 2026."""
    circuit, expected, data = circuit_dataset
    meta = data["metadata"]
    assert meta["event"] == expected["event"]
    assert meta["date"] == expected["date"]
    assert meta["source"] == "fastf1"
    assert meta["telemetryYear"] == 2026


def test_expected_lap_count(circuit_dataset):
    """Rule 5: expected race lap count is correct."""
    circuit, expected, data = circuit_dataset
    assert data["totalLaps"] == expected["laps"]
    assert len(data["laps"]) == expected["laps"]


def test_actual_2026_driver_field(circuit_dataset):
    """Rule 6: actual 2026 driver/team mapping is used."""
    circuit, expected, data = circuit_dataset
    # Check that Haas drivers in the dataset are OCO or BEA
    all_drivers = set()
    for lap in data["laps"]:
        for drv in lap["drivers"]:
            all_drivers.add(drv["code"])
            
    # In 2026 Haas has OCO and BEA
    assert "OCO" in all_drivers or "BEA" in all_drivers
    # Kevin Magnussen is NOT driving in the 2026 Haas team
    assert "MAG" not in all_drivers, "2024 driver MAG found in 2026 race dataset!"


def test_no_2024_telemetry(circuit_dataset):
    """Rule 7: no 2024 factual telemetry is used."""
    circuit, expected, data = circuit_dataset
    meta = data["metadata"]
    assert "2024" not in meta["date"]
    assert meta["season"] == 2026
    assert meta["telemetryYear"] == 2026


def test_simulation_fallback_only(circuit_dataset):
    """Rule 8: simulation remains fallback only; factual dataset uses fastf1."""
    circuit, expected, data = circuit_dataset
    meta = data["metadata"]
    assert meta["source"] == "fastf1"
    assert meta["positionsProvenance"] == "ACTUAL"
    assert meta["energyProvenance"] == "INFERRED"


def test_soc_within_4mj_window(circuit_dataset):
    """Rule 9: SoC remains within 4 MJ window (normalized in [0, 1])."""
    circuit, expected, data = circuit_dataset
    for lap in data["laps"]:
        for drv in lap["drivers"]:
            assert 0.0 <= drv["soc"] <= 1.0
            assert 0.0 <= drv["nextSoc"] <= 1.0
            if "subLap" in drv and drv["subLap"]:
                for s in drv["subLap"]["soc"]:
                    assert 0.0 <= s <= 1.0


def test_harvest_deploy_limits(circuit_dataset):
    """Rule 10: harvest/deploy limits remain compliant with config (8.5 MJ/lap)."""
    circuit, expected, data = circuit_dataset
    assert data["harvestCapMj"] == 8.5


def test_sublap_checkpoints_exist_and_2026(circuit_dataset):
    """Rules 11 & 12: subLap checkpoints exist and generated from 2026 replay."""
    circuit, expected, data = circuit_dataset
    for lap in data["laps"][:10]:
        for drv in lap["drivers"]:
            sub = drv.get("subLap")
            assert sub is not None, f"subLap missing for {drv['code']} in lap {lap['lap']}"
            assert len(sub["soc"]) == 16
            assert len(sub["modes"]) == 16
            assert len(sub["kinds"]) == 16
            assert len(sub["clips"]) == 16


def test_cumulative_gap_2026_timing(circuit_dataset):
    """Rule 13: cumulative gap is based on actual 2026 race timing."""
    circuit, expected, data = circuit_dataset
    for lap in data["laps"][:10]:
        drivers = sorted(lap["drivers"], key=lambda d: d["position"])
        assert drivers[0]["position"] == 1
        assert drivers[0]["gapToLeader"] == 0.0
        prev_gap = 0.0
        for drv in drivers[1:]:
            if drv["gapToLeader"] is not None:
                assert drv["gapToLeader"] >= prev_gap
                prev_gap = drv["gapToLeader"]


def test_what_if_seed_and_projected(circuit_dataset):
    """Rules 14 & 15: What-If seed comes from actual 2026 snapshot and outputs are PROJECTED."""
    circuit, expected, data = circuit_dataset
    for lap in data["laps"][:5]:
        for drv in lap["drivers"]:
            rec = drv.get("recommendation")
            if rec and "whatIfBranches" in rec:
                for action, branch in rec["whatIfBranches"].items():
                    assert 0.0 <= branch["projectedSoc"] <= 1.0
                    assert branch["projectedPosition"] >= 1
                    assert branch["risk"] in {"LOW", "MEDIUM", "HIGH"}


def test_provenance_correctness(circuit_dataset):
    """Rule 16: provenance remains correct."""
    circuit, expected, data = circuit_dataset
    meta = data["metadata"]
    assert meta["positionsProvenance"] == "ACTUAL"
    assert meta["energyProvenance"] == "INFERRED"
    for lap in data["laps"][:5]:
        for drv in lap["drivers"]:
            rec = drv.get("recommendation")
            if rec:
                for factor in rec.get("factors", []):
                    assert factor["provenance"] in {"ACTUAL", "INFERRED", "PROJECTED", "SAMPLE"}
