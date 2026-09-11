"""Filesystem layout, cache manifest and pre-caching.

The whole project is offline-first. ``pre_cache_sessions`` downloads (once) and
records a manifest so the app can prove, at demo time, that it is running from
local disk rather than a live feed.
"""

from __future__ import annotations

import json
import logging
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from raceiq.config import load_circuits

log = logging.getLogger(__name__)

__all__ = [
    "data_dir", "cache_dir", "raw_dir", "tracks_dir", "processed_dir",
    "manifest_path", "read_manifest", "write_manifest", "cache_status",
    "pre_cache_sessions",
]

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Endpoint list persisted for every pre-cached session.
OPENF1_CACHE_ENDPOINTS = (
    "drivers", "laps", "position", "intervals", "stints",
    "pit", "race_control", "weather",
)


def data_dir() -> Path:
    """``<repo>/data`` - honours ``RACEIQ_DATA_DIR``."""
    import os

    env = os.environ.get("RACEIQ_DATA_DIR")
    return Path(env) if env else _REPO_ROOT / "data"


def cache_dir() -> Path:
    """FastF1 HTTP cache directory."""
    return data_dir() / "cache"


def raw_dir() -> Path:
    """Raw OpenF1 downloads."""
    return data_dir() / "raw" / "openf1"


def tracks_dir() -> Path:
    """Local track geometry (TUMFTM / GeoJSON)."""
    return data_dir() / "tracks"


def processed_dir() -> Path:
    """Derived artefacts (segments, observer output, frontier caches)."""
    return data_dir() / "processed"


def manifest_path() -> Path:
    """Path of the cache manifest JSON."""
    return data_dir() / "cache_manifest.json"


def _ensure_dirs() -> None:
    for p in (cache_dir(), raw_dir(), tracks_dir(), processed_dir()):
        p.mkdir(parents=True, exist_ok=True)


def read_manifest() -> Dict[str, Any]:
    """Read the cache manifest; empty dict when absent."""
    p = manifest_path()
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):  # pragma: no cover - defensive
        return {}


def write_manifest(manifest: Dict[str, Any]) -> Path:
    """Persist the cache manifest and return its path."""
    _ensure_dirs()
    manifest.setdefault("generated_utc", datetime.now(timezone.utc).isoformat())
    p = manifest_path()
    with p.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    return p


def cache_status() -> Dict[str, Any]:
    """Summarise what is available offline right now."""
    man = read_manifest()
    events: Dict[str, Any] = {}
    for key, rec in man.get("sessions", {}).items():
        events[key] = {
            "fastf1": bool(rec.get("fastf1")),
            "telemetry_samples": int(rec.get("telemetry_samples", 0)),
            "drivers": int(rec.get("drivers", 0)),
            "openf1_endpoints": list(rec.get("openf1_endpoints", [])),
            "simulation_only": bool(rec.get("simulation_only", False)),
        }
    return {
        "data_dir": str(data_dir()),
        "manifest_present": bool(man),
        "generated_utc": man.get("generated_utc"),
        "sessions": events,
    }


def _count_telemetry_samples(session: Any) -> int:
    """Best-effort count of cached telemetry rows across all drivers."""
    total = 0
    try:
        laps = session.laps
    except Exception:  # pragma: no cover - defensive
        return 0
    if laps is None or len(laps) == 0:
        return 0
    for drv in list(laps["Driver"].unique()):
        try:
            fastest = laps[laps["Driver"] == drv].pick_fastest()
            if fastest is None or fastest is False:  # pragma: no cover
                continue
            total += len(fastest.get_car_data())
        except Exception:  # pragma: no cover - defensive
            continue
    return total


def pre_cache_sessions(
    events: Iterable[str],
    cache_dir_: Optional[str] = None,
    year: int = 2026,
    session: str = "R",
    with_openf1: bool = True,
) -> Dict[str, Any]:
    """Pre-cache FastF1 sessions and download OpenF1 tables.

    Parameters
    ----------
    events:
        Circuit keys from ``config/circuits.json`` (e.g. ``["Melbourne", ...]``).
    cache_dir_:
        Override for the FastF1 cache directory.
    with_openf1:
        Set False to skip network downloads of OpenF1 tables.

    Returns
    -------
    dict
        The updated manifest (also written to ``data/cache_manifest.json``).
    """
    import fastf1  # imported lazily so headless tests do not require it

    _ensure_dirs()
    target = Path(cache_dir_) if cache_dir_ else cache_dir()
    target.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fastf1.Cache.enable_cache(str(target))

    circuits = load_circuits()
    manifest = read_manifest()
    sessions = manifest.setdefault("sessions", {})

    for key in events:
        circ = circuits.get(key)
        if circ is None:
            log.warning("Unknown circuit key: %s", key)
            continue
        rec: Dict[str, Any] = sessions.setdefault(key, {})
        rec.update(
            {
                "circuit": key,
                "year": year,
                "session": session,
                "fastf1_event": circ.fastf1_event,
                "openf1_session_key": circ.openf1_session_key,
                "simulation_only": circ.simulation_only,
            }
        )

        # --- FastF1 -----------------------------------------------------
        try:
            s = fastf1.get_session(year, circ.fastf1_event, session)
            s.load(telemetry=True, laps=True, weather=False, messages=False)
            n_drivers = int(s.laps["Driver"].nunique())
            rec.update(
                {
                    "fastf1": True,
                    "drivers": n_drivers,
                    "total_laps": int(s.total_laps or 0),
                    "telemetry_samples": _count_telemetry_samples(s),
                    "event_name": getattr(s, "event", {}).get(
                        "EventName", circ.fastf1_event
                    )
                    if isinstance(getattr(s, "event", None), dict)
                    else circ.fastf1_event,
                }
            )
            log.info("cached %s: %d drivers", key, n_drivers)
        except Exception as exc:
            rec.update({"fastf1": False, "error": f"{type(exc).__name__}: {exc}"})
            log.warning("FastF1 cache failed for %s: %s", key, exc)

        # --- OpenF1 ------------------------------------------------------
        if with_openf1 and circ.openf1_session_key:
            try:
                from raceiq.ingest.openf1_client import download_session

                saved = download_session(
                    circ.openf1_session_key,
                    endpoints=OPENF1_CACHE_ENDPOINTS,
                    raw_dir_=str(raw_dir()),
                )
                rec["openf1_endpoints"] = sorted(saved.keys())
            except Exception as exc:  # pragma: no cover - network dependent
                rec["openf1_endpoints"] = []
                rec["openf1_error"] = f"{type(exc).__name__}: {exc}"
                log.warning("OpenF1 download failed for %s: %s", key, exc)

        rec["cached_utc"] = datetime.now(timezone.utc).isoformat()

    write_manifest(manifest)
    return manifest
