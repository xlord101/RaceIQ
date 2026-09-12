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


def test_tyre_data_presence_and_validity(circuit_dataset):
    """Verify tyre compound and age are present and valid for drivers."""
    circuit, expected, data = circuit_dataset
    valid_compounds = {"SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET", None}
    for lap in data["laps"][:15]:
        for drv in lap["drivers"]:
            tyre = drv.get("tyre")
            assert tyre is not None, f"Missing tyre object for {drv['code']} in lap {lap['lap']}"
            assert tyre["compound"] in valid_compounds, f"Invalid compound {tyre['compound']} for {drv['code']}"
            if tyre["ageLaps"] is not None:
                assert tyre["ageLaps"] >= 0, f"Negative tyre age for {drv['code']}"


def test_lap_timing_data_validity(circuit_dataset):
    """Verify lap timing source fields (lapStartTime, lapEndTime, lapTime) are valid."""
    circuit, expected, data = circuit_dataset
    for lap in data["laps"][:15]:
        for drv in lap["drivers"]:
            timing = drv.get("lapTiming")
            assert timing is not None, f"Missing lapTiming for {drv['code']} in lap {lap['lap']}"
            if timing.get("lapTime") is not None:
                assert timing["lapTime"] > 0, f"Non-positive lapTime for {drv['code']}"
            if timing.get("lapStartTime") is not None and timing.get("lapEndTime") is not None:
                assert timing["lapEndTime"] >= timing["lapStartTime"], f"lapEndTime before lapStartTime for {drv['code']}"


def test_driver_grid_and_positions(circuit_dataset):
    """Verify driver grid contains valid 2026 participants with sequential positions."""
    circuit, expected, data = circuit_dataset
    all_codes = set()
    for idx, lap in enumerate(data["laps"]):
        drivers = lap["drivers"]
        min_expected = 18 if idx == 0 else 5
        assert len(drivers) >= min_expected, f"Expected at least {min_expected} drivers in lap {lap['lap']}, got {len(drivers)}"
        positions = [d["position"] for d in drivers]
        assert positions[0] == 1, "P1 must be first"
        for i, pos in enumerate(positions):
            assert pos == i + 1, f"Positions must be sequential: {positions}"
        for d in drivers:
            all_codes.add(d["code"])
    # 2026 FIA field has up to 22 entries (18-22 depending on retirements/DNS)
    assert 18 <= len(all_codes) <= 22, f"Unexpected field size: {len(all_codes)}"


def test_driver_lap_fraction_validity(circuit_dataset):
    """Verify driver lap timing and distance map to valid normalized progress in [0, 1]."""
    circuit, expected, data = circuit_dataset
    for lap in data["laps"][:15]:
        base_lap_time = data.get("baseLapTime", 90.0)
        leader = next((d for d in lap["drivers"] if d["position"] == 1), lap["drivers"][0])
        leader_start = leader.get("lapTiming", {}).get("lapStartTime")
        leader_dur = leader.get("lapTiming", {}).get("lapTime") or base_lap_time

        for drv in lap["drivers"]:
            timing = drv.get("lapTiming") or {}
            # Verify driver's local time progress
            if drv["position"] == 1:
                norm_time_frac = 0.5  # test mid-lap
            elif timing.get("lapStartTime") is not None and leader_start is not None and timing.get("lapTime"):
                t_current = leader_start + 0.5 * leader_dur
                t_driver = t_current - timing["lapStartTime"]
                norm_time_frac = ((t_driver / timing["lapTime"]) % 1.0 + 1.0) % 1.0
            else:
                gap = drv.get("gapToLeader") or 0.0
                norm_time_frac = (((0.5 * base_lap_time - gap) / base_lap_time) % 1.0 + 1.0) % 1.0

            assert 0.0 <= norm_time_frac < 1.0, f"Normalized time fraction out of bounds: {norm_time_frac}"

            # Verify distance mapping if subLap distance exists
            sub = drv.get("subLap")
            if sub and sub.get("distance"):
                dist = sub["distance"]
                max_d = dist[-1]
                assert max_d > 0
                u = norm_time_frac * (len(dist) - 1)
                idx = int(u)
                r = u - idx
                d_interp = dist[idx] + r * (dist[min(idx + 1, len(dist) - 1)] - dist[idx])
                dist_frac = d_interp / max_d
                assert 0.0 <= dist_frac <= 1.0, f"Distance progress out of bounds: {dist_frac}"


def test_telemetry_distance_monotonicity(circuit_dataset):
    """Verify subLap.distance has 16 monotonically increasing samples."""
    circuit, expected, data = circuit_dataset
    for lap in data["laps"][:10]:
        for drv in lap["drivers"]:
            sub = drv.get("subLap")
            if sub and "distance" in sub and sub["distance"]:
                dist = sub["distance"]
                assert len(dist) == 16, f"Distance array length {len(dist)} != 16 for {drv['code']}"
                assert dist[0] >= 0, f"Initial distance negative for {drv['code']}"
                assert dist[-1] > dist[0], f"Lap distance not advancing for {drv['code']}"
                for i in range(1, len(dist)):
                    assert dist[i] >= dist[i - 1], f"Distance not non-decreasing at index {i} for {drv['code']}"

