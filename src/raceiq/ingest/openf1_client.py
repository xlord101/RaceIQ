"""OpenF1 client (gaps, positions, stints, pit, SC/VSC, weather).

OpenF1 exposes **no** SoC / MGU-K / ERS / Active Aero channel - that is exactly
why RaceIQ has to estimate them. See the Nitrous devlog (31 Mar 2026) and FIA
Art. 8.5 confidentiality.

All downloads are written under ``data/raw/openf1`` so the pipeline runs offline.
Network failures never raise: they return an empty DataFrame and set
``offline=True`` on the module-level status dict.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import requests

from raceiq.ingest.cache_manager import raw_dir

log = logging.getLogger(__name__)

__all__ = [
    "OPENF1_BASE",
    "OPENF1_ENDPOINTS",
    "fetch_openf1",
    "download_session",
    "load_openf1_local",
    "session_key_for",
    "status",
]

OPENF1_BASE = "https://api.openf1.org/v1"

#: Endpoints used by RaceIQ. ``car_data`` is the telemetry fallback used when
#: FastF1 has no data for a session (e.g. Bahrain 2026).
OPENF1_ENDPOINTS = (
    "sessions", "drivers", "laps", "car_data", "position", "intervals",
    "stints", "pit", "race_control", "weather", "meetings",
)

#: Populated at runtime so the UI can display "OFFLINE / CACHED" honestly.
status: Dict[str, Any] = {"offline": False, "last_error": None, "requests": 0}


def _get(endpoint: str, params: Dict[str, Any], timeout: float) -> Any:
    url = f"{OPENF1_BASE}/{endpoint}"
    status["requests"] += 1
    resp = requests.get(url, params={**params, "format": "csv"}, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def fetch_openf1(
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 20.0,
) -> pd.DataFrame:
    """Fetch one OpenF1 endpoint and return it as a DataFrame.

    Parameters
    ----------
    endpoint:
        e.g. ``"intervals"``, ``"position"``, ``"stints"``.
    params:
        Query parameters, typically ``{"session_key": 11234}``.

    Returns
    -------
    pandas.DataFrame
        Empty DataFrame (with ``offline`` flagged in :data:`status`) if the
        request fails, so callers degrade gracefully instead of crashing.
    """
    params = dict(params or {})
    try:
        text = _get(endpoint, params, timeout)
        status["offline"] = False
        if not text.strip():
            return pd.DataFrame()
        return pd.read_csv(pd.io.common.StringIO(text))  # type: ignore[attr-defined]
    except Exception as exc:
        status["offline"] = True
        status["last_error"] = f"{type(exc).__name__}: {exc}"
        log.warning("OpenF1 fetch failed (%s): %s", endpoint, exc)
        return pd.DataFrame()


def _raw_path(session_key: int, endpoint: str, raw_dir_: Optional[str] = None) -> Path:
    base = Path(raw_dir_) if raw_dir_ else raw_dir()
    return base / str(session_key) / f"{endpoint}.csv"


def download_session(
    session_key: int,
    endpoints: Iterable[str] = ("drivers", "laps", "position", "intervals", "stints"),
    raw_dir_: Optional[str] = None,
    timeout: float = 60.0,
) -> Dict[str, Path]:
    """Download and persist OpenF1 tables for one session.

    Returns a mapping ``endpoint -> path`` for every non-empty download.
    """
    saved: Dict[str, Path] = {}
    for ep in endpoints:
        df = fetch_openf1(ep, {"session_key": session_key}, timeout=timeout)
        if df.empty:
            continue
        path = _raw_path(session_key, ep, raw_dir_)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        saved[ep] = path
    return saved


def load_openf1_local(
    session_key: int,
    endpoint: str,
    raw_dir_: Optional[str] = None,
) -> pd.DataFrame:
    """Load a previously downloaded OpenF1 table from disk (offline path)."""
    path = _raw_path(session_key, endpoint, raw_dir_)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("Failed to read %s: %s", path, exc)
        return pd.DataFrame()


def session_key_for(year: int, event: str) -> Optional[int]:
    """Resolve an OpenF1 ``session_key`` for a race.

    Uses ``config/circuits.json`` first (no network), then falls back to
    querying the OpenF1 ``sessions`` endpoint.
    """
    from raceiq.config import load_circuits

    circuits = load_circuits()
    for cfg in circuits.values():
        if cfg.fastf1_event.lower() == event.lower() or cfg.key.lower() == event.lower():
            if cfg.openf1_session_key:
                return cfg.openf1_session_key

    df = fetch_openf1("sessions", {"year": year, "session_name": "Race"})
    if df.empty:
        return None
    mask = df.get("circuit_short_name", pd.Series(dtype=str)).astype(str).str.contains(
        event, case=False, na=False
    )
    if not mask.any():
        mask = df.get("location", pd.Series(dtype=str)).astype(str).str.contains(
            event, case=False, na=False
        )
    if not mask.any():
        return None
    return int(df.loc[mask, "session_key"].iloc[0])


def list_openf1_sessions(year: int) -> pd.DataFrame:
    """Convenience wrapper: every session OpenF1 knows about for a year."""
    return fetch_openf1("sessions", {"year": year})
