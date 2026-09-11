"""Phase 1 tests: ingest (FastF1 cache + OpenF1 + offline degradation)."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from raceiq.ingest import (
    cache_dir,
    data_dir,
    get_lap_telemetry,
    load_fastf1_session,
    manifest_path,
    pre_cache_sessions,
    read_manifest,
)
from raceiq.ingest import openf1_client as of1

REPO = Path(__file__).resolve().parents[1]
REQUIRED_EVENTS = ("Melbourne", "Shanghai", "Monza")


def _has_cache() -> bool:
    return cache_dir().exists() and any(cache_dir().iterdir())


def _cached(event: str) -> bool:
    man = read_manifest()
    return bool(man.get("sessions", {}).get(event, {}).get("fastf1"))


needs_cache = pytest.mark.skipif(not _has_cache(), reason="FastF1 cache not present")
needs_melbourne = pytest.mark.skipif(not _cached("Melbourne"), reason="Melbourne not cached")


# ---------------------------------------------------------------------------
# Offline / no-network behaviour (always runs)
# ---------------------------------------------------------------------------


def test_data_dirs_exist():
    assert data_dir().exists()
    assert cache_dir().exists()
    assert manifest_path().parent.exists()


def test_openf1_fetch_degrades_offline(monkeypatch):
    """A network failure must yield an empty frame, never an exception."""

    def boom(*a, **k):
        raise RuntimeError("no network")

    monkeypatch.setattr(of1.requests, "get", boom)
    df = of1.fetch_openf1("intervals", {"session_key": 11234})
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert of1.status["offline"] is True


def test_openf1_parses_csv(monkeypatch):
    class _Resp:
        status_code = 200
        text = "session_key,driver_number,gap\n11234,1,0.4\n11234,4,1.2\n"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(of1.requests, "get", lambda *a, **k: _Resp())
    df = of1.fetch_openf1("intervals", {"session_key": 11234})
    assert len(df) == 2
    assert list(df.columns) == ["session_key", "driver_number", "gap"]
    assert of1.status["offline"] is False


def test_openf1_local_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("RACEIQ_DATA_DIR", str(tmp_path))
    df = pd.DataFrame({"a": [1, 2]})
    saved = of1.download_session.__wrapped__ if hasattr(of1.download_session, "__wrapped__") else None
    # write directly through the same path helper semantics
    p = tmp_path / "raw" / "openf1" / "999" / "laps.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False)
    back = of1.load_openf1_local(999, "laps")
    assert len(back) == 2


def test_session_key_for_uses_config_no_network(monkeypatch):
    """circuits.json resolves keys without touching the network."""
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise RuntimeError("offline")

    monkeypatch.setattr(of1, "fetch_openf1", boom)
    assert of1.session_key_for(2026, "Melbourne") == 11234
    assert of1.session_key_for(2026, "Monza") == 11361
    assert called["n"] == 0


def test_manifest_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("RACEIQ_DATA_DIR", str(tmp_path))
    from raceiq.ingest import cache_manager as cm

    cm.write_manifest({"sessions": {"X": {"fastf1": True}}})
    man = cm.read_manifest()
    assert man["sessions"]["X"]["fastf1"] is True
    status = cm.cache_status()
    assert status["manifest_present"] is True
    assert "X" in status["sessions"]


def test_pre_cache_reports_failure_without_raising(tmp_path, monkeypatch):
    """An unknown circuit must be reported, not crash the runner."""
    monkeypatch.setenv("RACEIQ_DATA_DIR", str(tmp_path))
    man = pre_cache_sessions(["DoesNotExist"], with_openf1=False)
    assert "DoesNotExist" not in man.get("sessions", {})


# ---------------------------------------------------------------------------
# Real cached session (skipped when not pre-cached)
# ---------------------------------------------------------------------------


@needs_cache
@needs_melbourne
def test_load_melbourne_session():
    s = load_fastf1_session(2026, "Melbourne", "R")
    assert s.year == 2026
    assert s.circuit_key == "Melbourne"
    assert s.total_laps > 20
    assert len(s.drivers) >= 18, s.drivers
    assert len(s.laps) > 100
    assert {"Driver", "LapNumber", "LapTime", "Team"} <= set(s.laps.columns)
    assert s.track_length_m > 4000


@needs_cache
@needs_melbourne
def test_driver_info_has_teams():
    s = load_fastf1_session(2026, "Melbourne", "R")
    assert len(s.driver_info) >= 18
    assert s.driver_info["Team"].astype(str).str.len().gt(0).all()
    for d in s.drivers[:5]:
        assert s.driver_team(d)


@needs_cache
@needs_melbourne
def test_lap_telemetry_channels():
    s = load_fastf1_session(2026, "Melbourne", "R")
    drv = s.drivers[0]
    tel = get_lap_telemetry(s, drv, resample_m=10.0)
    assert not tel.empty
    for col in ("Distance", "Speed", "Throttle", "Brake"):
        assert col in tel.columns
    # public channels only - never an ERS/SoC channel
    banned = {"SoC", "SOC", "MGUK", "MGU_K", "ERS", "Energy", "Battery"}
    assert not banned & set(tel.columns)
    # throttle normalised to 0..1, brake boolean-ish
    assert tel["Throttle"].min() >= 0.0
    assert tel["Throttle"].max() <= 1.0
    assert tel["Brake"].isin([0.0, 1.0]).all()
    # speed in a plausible F1 range
    assert tel["Speed"].max() > 200
    assert tel["Speed"].max() < 400


@needs_cache
@needs_melbourne
def test_lap_telemetry_resample_uniform():
    s = load_fastf1_session(2026, "Melbourne", "R")
    drv = s.drivers[0]
    tel = get_lap_telemetry(s, drv, resample_m=25.0)
    steps = np.diff(tel["Distance"].to_numpy())
    assert np.allclose(steps, 25.0, atol=1e-6)
    assert tel["Distance"].is_monotonic_increasing


@needs_cache
@needs_melbourne
def test_telemetry_distance_covers_lap():
    s = load_fastf1_session(2026, "Melbourne", "R")
    drv = s.drivers[0]
    tel = get_lap_telemetry(s, drv)
    span = tel["Distance"].max() - tel["Distance"].min()
    assert span > 0.85 * s.track_length_m, (span, s.track_length_m)


@needs_cache
@needs_melbourne
def test_missing_lap_returns_empty():
    s = load_fastf1_session(2026, "Melbourne", "R")
    assert get_lap_telemetry(s, "ZZZ", 1).empty
    assert get_lap_telemetry(s, s.drivers[0], 9999).empty


@needs_cache
def test_all_required_events_cached():
    man = read_manifest()
    for ev in REQUIRED_EVENTS:
        assert man.get("sessions", {}).get(ev, {}).get("fastf1"), f"{ev} not cached"
