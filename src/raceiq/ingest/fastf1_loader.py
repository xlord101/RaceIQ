"""FastF1 session loading and lap-telemetry extraction.

Primary source is the local FastF1 cache (offline-first). When FastF1 has no
telemetry for a session (Bahrain 2026 is one such case) the loader falls back to
OpenF1 ``car_data``, integrating speed over time to recover distance (OpenF1 has
no distance channel).

The loader deliberately exposes **only public channels**: Speed, RPM, Throttle,
Brake, Gear, Time, Distance. There is no SoC / MGU-K / ERS / Active Aero
channel in any public feed - that is the premise of RaceIQ. FastF1 downloads
may surface a legacy pre-2026 'drs' channel (the concept was replaced in 2026
by Active Aero + Overtake Mode); the 2026 pipeline ignores it.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from raceiq.config import load_circuits
from raceiq.ingest.cache_manager import cache_dir

log = logging.getLogger(__name__)

__all__ = [
    "SessionData",
    "load_fastf1_session",
    "get_lap_telemetry",
    "list_cached_events",
    "TELEMETRY_COLUMNS",
]

#: Public telemetry channels. No ERS/SoC channel exists in any public feed.
TELEMETRY_COLUMNS = (
    "Distance", "Speed", "RPM", "Throttle", "Brake", "nGear", "Time", "SessionTime",
)


@dataclass
class SessionData:
    """A cleaned, offline-usable race session."""

    year: int
    event: str
    session: str
    circuit_key: str
    laps: pd.DataFrame
    drivers: List[str]
    driver_info: pd.DataFrame
    total_laps: int
    track_length_m: float
    circuit_info: Dict[str, Any] = field(default_factory=dict)
    source: str = "fastf1"
    simulation_only: bool = False
    notes: List[str] = field(default_factory=list)
    _ff1: Any = field(default=None, repr=False)

    # ------------------------------------------------------------------
    def driver_team(self, driver: str) -> str:
        """Team name for a three-letter driver code."""
        row = self.driver_info[self.driver_info["Driver"] == driver]
        return str(row["Team"].iloc[0]) if len(row) else ""

    def driver_number(self, driver: str) -> Optional[int]:
        """Car number for a three-letter driver code."""
        row = self.driver_info[self.driver_info["Driver"] == driver]
        if not len(row):
            return None
        try:
            return int(row["DriverNumber"].iloc[0])
        except (ValueError, TypeError):  # pragma: no cover - defensive
            return None

    def has_telemetry(self, driver: str) -> bool:
        """True when lap data exists for this driver."""
        return bool((self.laps["Driver"] == driver).any())

    def fastest_lap_number(self, driver: str) -> Optional[int]:
        """Fastest (accurate) lap number for a driver, else any lap."""
        dl = self.laps[self.laps["Driver"] == driver]
        if not len(dl):
            return None
        acc = dl[dl.get("IsAccurate", pd.Series(True, index=dl.index)).astype(bool)]
        pool = acc if len(acc) else dl
        valid = pool[pool["LapTime"].notna()]
        if not len(valid):
            return int(pool["LapNumber"].iloc[0])
        idx = valid["LapTime"].idxmin()
        return int(valid.loc[idx, "LapNumber"])

    def lap_time_s(self, driver: str, lap_number: int) -> Optional[float]:
        """Lap time in seconds, or None."""
        dl = self.laps[
            (self.laps["Driver"] == driver) & (self.laps["LapNumber"] == lap_number)
        ]
        if not len(dl):
            return None
        val = dl["LapTime"].iloc[0]
        if pd.isna(val):
            return None
        return float(pd.Timedelta(val).total_seconds())


def _session_lap_frame(s: Any) -> pd.DataFrame:
    """Return the laps DataFrame with plain python types where needed."""
    laps: pd.DataFrame = s.laps.copy()
    if "Driver" not in laps.columns:  # pragma: no cover - defensive
        raise RuntimeError("session has no laps")
    return laps


def _driver_info(s: Any, laps: pd.DataFrame) -> pd.DataFrame:
    """Build a driver/team/number table from whatever the session offers."""
    rows: List[Dict[str, Any]] = []

    # FastF1 3.x exposes driver numbers on the session; try several sources.
    numbers: Sequence[str] = tuple(getattr(s, "drivers", ()) or ())
    info: Any = getattr(s, "driver_info", None)

    for num in numbers:
        code: Optional[str] = None
        team: Optional[str] = None
        name: Optional[str] = None
        if info is not None:
            try:
                rec = info[str(num)] if hasattr(info, "__getitem__") else None
                if rec is not None:
                    code = rec.get("Abbreviation") or rec.get("Tla")
                    team = rec.get("TeamName")
                    name = f"{rec.get('FirstName', '')} {rec.get('LastName', '')}".strip()
            except Exception:  # pragma: no cover - defensive
                pass
        if code is None:
            match = laps[laps["DriverNumber"].astype(str) == str(num)]
            if len(match):
                code = str(match["Driver"].iloc[0])
                team = str(match["Team"].iloc[0])
        if code is None:  # pragma: no cover - defensive
            continue
        rows.append(
            {
                "Driver": code,
                "DriverNumber": int(num),
                "Team": team or "",
                "FullName": name or code,
            }
        )

    if not rows:  # pragma: no cover - fall back to laps table
        for code, grp in laps.groupby("Driver"):
            rows.append(
                {
                    "Driver": str(code),
                    "DriverNumber": int(grp["DriverNumber"].iloc[0])
                    if "DriverNumber" in grp
                    else 0,
                    "Team": str(grp["Team"].iloc[0]) if "Team" in grp else "",
                    "FullName": str(code),
                }
            )
    return pd.DataFrame(rows).drop_duplicates("Driver").reset_index(drop=True)


def _circuit_info_dict(s: Any) -> Dict[str, Any]:
    """Extract corner geometry + rotation for the track map."""
    out: Dict[str, Any] = {"corners": None, "rotation": 0.0}
    try:
        ci = s.get_circuit_info()
    except Exception:  # pragma: no cover - defensive
        return out
    try:
        out["rotation"] = float(ci.rotation)
    except Exception:  # pragma: no cover - defensive
        pass
    try:
        corners = ci.corners
        if corners is not None and len(corners):
            out["corners"] = corners.copy()
    except Exception:  # pragma: no cover - defensive
        pass
    return out


def _openf1_telemetry(session_key: int, driver_number: int, year: int, event: str):
    """Fallback path: build a laps/telemetry structure from OpenF1 ``car_data``.

    OpenF1 has no distance channel, so distance is recovered by integrating
    speed over time. Used when FastF1 has no telemetry for a session.
    """
    from raceiq.ingest.openf1_client import fetch_openf1

    car = fetch_openf1("car_data", {"session_key": session_key, "driver_number": driver_number})
    if car.empty:
        return None
    car = car.sort_values("date")
    t = pd.to_datetime(car["date"], errors="coerce", utc=True)
    dt = t.diff().dt.total_seconds().fillna(0.0).clip(lower=0.0).to_numpy()
    speed = pd.to_numeric(car.get("speed"), errors="coerce").fillna(0.0).to_numpy()
    dist = np.cumsum(speed / 3.6 * dt)

    tel = pd.DataFrame(
        {
            "Distance": dist,
            "Speed": speed,
            "RPM": pd.to_numeric(car.get("rpm"), errors="coerce").fillna(0.0).to_numpy(),
            "Throttle": pd.to_numeric(car.get("throttle"), errors="coerce").fillna(0.0).to_numpy(),
            "Brake": pd.to_numeric(car.get("brake"), errors="coerce").fillna(0.0).to_numpy(),
            "nGear": pd.to_numeric(car.get("n_gear"), errors="coerce").fillna(0.0).to_numpy(),
            "Time": np.cumsum(dt),
        }
    )
    laps = pd.DataFrame(
        [
            {
                "Driver": str(driver_number),
                "DriverNumber": driver_number,
                "LapNumber": 1,
                "LapTime": pd.NaT,
                "Team": "",
            }
        ]
    )
    return laps, {str(driver_number): tel}


def load_fastf1_session(
    year: int,
    event: str,
    session: str = "R",
    cache_dir_: Optional[str] = None,
    with_telemetry: bool = True,
    allow_openf1_fallback: bool = True,
) -> SessionData:
    """Load a cached race session.

    Parameters
    ----------
    year, event, session:
        FastF1 identifiers, e.g. ``(2026, "Melbourne", "R")``.
    cache_dir_:
        FastF1 cache directory; defaults to ``data/cache``.
    with_telemetry:
        Load car telemetry (slower first time, cached afterwards).
    allow_openf1_fallback:
        Try OpenF1 ``car_data`` when FastF1 exposes no telemetry for the session.

    Returns
    -------
    SessionData
    """
    import fastf1

    circuits = load_circuits()
    circuit_key = event
    for k, c in circuits.items():
        if c.fastf1_event.lower() == event.lower() or k.lower() == event.lower():
            circuit_key = k
            break
    circ = circuits.get(circuit_key)

    target = Path(cache_dir_) if cache_dir_ else cache_dir()
    target.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fastf1.Cache.enable_cache(str(target))
        s = fastf1.get_session(year, event, session)
        try:
            s.load(telemetry=with_telemetry, laps=True, weather=False, messages=False)
        except Exception as exc:
            log.warning("FastF1 load raised for %s %s: %s", year, event, exc)

    notes: List[str] = []
    try:
        laps = _session_lap_frame(s)
    except Exception as exc:
        laps = pd.DataFrame()
        notes.append(f"no laps: {type(exc).__name__}: {exc}")

    info = _driver_info(s, laps) if len(laps) else pd.DataFrame()
    n_drivers = len(laps["Driver"].unique()) if len(laps) else 0

    if n_drivers == 0 and allow_openf1_fallback:
        key = circ.openf1_session_key if circ else None
        if key:
            notes.append("FastF1 telemetry unavailable; falling back to OpenF1 car_data.")
            frames = {}
            lap_rows = []
            for num in (list(getattr(s, "drivers", ())) or [])[:22]:
                got = _openf1_telemetry(key, int(num), year, event)
                if got is None:
                    continue
                l, tel = got
                lap_rows.append(l.iloc[0].to_dict())
                frames.update(tel)
            if lap_rows:
                laps = pd.DataFrame(lap_rows)
                info = _driver_info(s, laps)
                n_drivers = len(laps)

    total_laps = int(getattr(s, "total_laps", 0) or 0)
    if not total_laps and len(laps):
        total_laps = int(pd.to_numeric(laps["LapNumber"], errors="coerce").max() or 0)

    track_len = float(circ.lap_length_m) if circ else 5000.0

    return SessionData(
        year=year,
        event=event,
        session=session,
        circuit_key=circuit_key,
        laps=laps,
        drivers=sorted(info["Driver"].tolist()) if len(info) else [],
        driver_info=info,
        total_laps=total_laps,
        track_length_m=track_len,
        circuit_info=_circuit_info_dict(s) if len(laps) else {},
        source="fastf1" if n_drivers else "empty",
        simulation_only=bool(circ.simulation_only) if circ else False,
        notes=notes,
        _ff1=s,
    )


def get_lap_telemetry(
    data: SessionData,
    driver: str,
    lap_number: Optional[int] = None,
    resample_m: Optional[float] = None,
) -> pd.DataFrame:
    """Return one driver's telemetry for one lap.

    Parameters
    ----------
    data:
        Loaded session.
    driver:
        Three-letter code.
    lap_number:
        Lap to extract; defaults to the driver's fastest lap.
    resample_m:
        If given, interpolate onto a uniform distance grid of this spacing.

    Returns
    -------
    pandas.DataFrame
        Columns ``Distance, Speed, RPM, Throttle, Brake, nGear, Time``. Empty
        when the driver/lap has no data.
    """
    if data._ff1 is None or not len(data.laps):
        return pd.DataFrame(columns=list(TELEMETRY_COLUMNS))

    dl = data.laps[data.laps["Driver"] == driver]
    if not len(dl):
        return pd.DataFrame(columns=list(TELEMETRY_COLUMNS))

    if lap_number is None:
        lap_number = data.fastest_lap_number(driver)
        if lap_number is None:
            return pd.DataFrame(columns=list(TELEMETRY_COLUMNS))

    match = dl[dl["LapNumber"] == lap_number]
    if not len(match):
        return pd.DataFrame(columns=list(TELEMETRY_COLUMNS))

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lap = match.iloc[0]
            tel = lap.get_car_data().add_distance()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("telemetry extraction failed %s L%s: %s", driver, lap_number, exc)
        return pd.DataFrame(columns=list(TELEMETRY_COLUMNS))

    tel = tel.reset_index(drop=True)
    keep = [c for c in TELEMETRY_COLUMNS if c in tel.columns]
    tel = tel[keep].copy()
    for c in ("Speed", "RPM", "Throttle", "Brake", "nGear", "Distance"):
        if c in tel.columns:
            tel[c] = pd.to_numeric(tel[c], errors="coerce")
    if "Time" in tel.columns:
        tel["Time"] = pd.to_timedelta(tel["Time"], errors="coerce").dt.total_seconds()
    tel = tel.dropna(subset=["Distance", "Speed"])
    tel = tel.sort_values("Distance").reset_index(drop=True)

    # Throttle arrives as 0-100 in FastF1; normalise to 0-1 for our models.
    if "Throttle" in tel.columns and tel["Throttle"].max() > 1.5:
        tel["Throttle"] = tel["Throttle"] / 100.0
    if "Brake" in tel.columns:
        tel["Brake"] = (tel["Brake"].fillna(0).astype(float) > 0).astype(float)

    if resample_m and len(tel) > 3:
        tel = _resample_by_distance(tel, float(resample_m))
    return tel


def _resample_by_distance(tel: pd.DataFrame, step_m: float) -> pd.DataFrame:
    """Interpolate telemetry onto a uniform distance grid.

    Continuous channels (Speed, RPM, Throttle, nGear, Time) are linearly
    interpolated; the Brake channel is an on/off flag, so it is resampled by
    nearest-neighbour and snapped back to 0/1 rather than averaged into a
    fraction.
    """
    d0 = float(tel["Distance"].min())
    d1 = float(tel["Distance"].max())
    if not np.isfinite(d0) or not np.isfinite(d1) or d1 - d0 < step_m * 2:
        return tel
    grid = np.arange(d0, d1, step_m)
    out = {"Distance": grid}
    for col in ("Speed", "RPM", "Throttle", "nGear", "Time"):
        if col in tel.columns:
            out[col] = np.interp(grid, tel["Distance"].to_numpy(), tel[col].to_numpy())
    if "Brake" in tel.columns:
        out["Brake"] = np.round(
            np.interp(grid, tel["Distance"].to_numpy(), tel["Brake"].to_numpy())
        ).astype(float)
    return pd.DataFrame(out)


def list_cached_events() -> List[str]:
    """Circuit keys that have a FastF1 cache entry, per the manifest."""
    from raceiq.ingest.cache_manager import read_manifest

    man = read_manifest()
    return [k for k, v in man.get("sessions", {}).items() if v.get("fastf1")]
