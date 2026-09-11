"""Shared fixtures for the RaceIQ test suite.

Anything that needs the pre-cached 2026 FastF1 sessions is skipped when the
cache is absent, so the suite still runs cleanly on a fresh clone.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pytest

from raceiq.config import RulesConfig, load_rules
from raceiq.track.segmentation import build_segments
from raceiq.types import Segment

REPO = Path(__file__).resolve().parents[1]


def _cache_present() -> bool:
    """True when at least one 2026 session has been pre-cached."""
    from raceiq.ingest import cache_dir

    try:
        return cache_dir().exists() and any(cache_dir().iterdir())
    except Exception:
        return False


needs_cache = pytest.mark.skipif(
    not _cache_present(), reason="requires pre-cached FastF1 sessions (scripts/pre_cache.py)"
)


@pytest.fixture(scope="session")
def rules() -> RulesConfig:
    """Loaded FIA 2026 rules (no network, no cache)."""
    return load_rules()


def _synthetic_segments(rules: RulesConfig) -> List[Segment]:
    """A deterministic 3 km lap: braking zone, exit, straight, coast.

    Used by tests that must run without any cached data.
    """
    from raceiq.track.segmentation import mark_key_acceleration_zones

    spec = [
        ("straight", 320.0, 700.0),
        ("brake", 300.0, 90.0),
        ("exit", 120.0, 230.0),
        ("coast", 220.0, 210.0),
        ("straight", 300.0, 330.0),
        ("brake", 320.0, 100.0),
        ("exit", 140.0, 260.0),
        ("coast", 280.0, 250.0),
    ]
    segs: List[Segment] = []
    dist = 0.0
    idx = 0
    for kind, length, speed in spec:
        n = max(int(length // rules.segment_length_m), 1)
        step = length / n
        for k in range(n):
            v_in = speed - 0.5 * (k / n) * 0.0
            v_out = speed
            harvest = 0.0
            if kind == "brake":
                from raceiq.physics import harvest_energy_mj

                v_in = speed * (1.0 - 0.55 * (k + 1) / n)
                v_out = speed * (1.0 - 0.55 * (k + 2) / n)
                harvest = harvest_energy_mj(v_in, v_out, rules.physics)
            segs.append(
                Segment(
                    index=idx,
                    start_m=dist,
                    end_m=dist + step,
                    kind=kind,
                    mean_speed_kph=0.5 * (v_in + v_out),
                    entry_speed_kph=v_in,
                    exit_speed_kph=v_out,
                    harvest_potential_mj=harvest,
                )
            )
            dist += step
            idx += 1
    return mark_key_acceleration_zones(segs, n_zones=2, min_length_m=150.0)


@pytest.fixture(scope="session")
def synthetic_segments(rules: RulesConfig) -> List[Segment]:
    """Cache-free stand-in lap for solver and ledger tests."""
    return _synthetic_segments(rules)


@pytest.fixture(scope="session")
def cached_events() -> List[str]:
    """Events that actually have telemetry in the local cache."""
    try:
        from raceiq.ingest import read_manifest

        man = read_manifest()
        return sorted(
            k for k, v in (man.get("sessions") or {}).items() if v.get("fastf1")
        )
    except Exception:
        return []


@pytest.fixture(scope="session")
def replay(cached_events: List[str], rules: RulesConfig):
    """Replay of the first cached event, or ``None`` when nothing is cached."""
    if not cached_events:
        return None
    from raceiq.pipeline import build_replay

    return build_replay(cached_events[0], 2026, "R", rules)


@pytest.fixture(scope="session")
def real_segments(replay) -> Optional[List[Segment]]:
    """10 m segments from real cached telemetry, or ``None``."""
    return None if replay is None else replay.segments
