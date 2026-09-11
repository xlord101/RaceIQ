"""End-to-end replay pipeline: session -> segments -> estimated SoC field.

This is the object the UI, the baselines and the decision engine all consume.
It is deliberately lazy and cached: the expensive per-driver observer run
happens once and is reused.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from raceiq.config import EventConfig, RulesConfig, load_event, load_rules
from raceiq.ingest import SessionData, get_lap_telemetry, load_fastf1_session
from raceiq.inference.clipping import clipping_flags
from raceiq.inference.soc_observer import SocObserver
from raceiq.track.segmentation import (
    longest_straight,
    segments_from_telemetry,
    segments_to_frame,
)
from raceiq.types import Segment

log = logging.getLogger(__name__)

__all__ = ["ReplaySession", "build_replay"]


@dataclass
class ReplaySession:
    """A loaded race ready for replay, decision-making and charts."""

    data: SessionData
    rules: RulesConfig
    event_cfg: EventConfig
    segments: List[Segment] = field(default_factory=list)
    telemetry: Dict[str, pd.DataFrame] = field(default_factory=dict)
    laps_soc: pd.DataFrame = field(default_factory=pd.DataFrame)
    profiles: Dict[str, pd.DataFrame] = field(default_factory=dict)
    aggression: Dict[str, float] = field(default_factory=dict)

    # ------------------------------------------------------------------
    @property
    def event(self) -> str:
        """Circuit key."""
        return self.data.circuit_key

    @property
    def total_laps(self) -> int:
        """Number of laps in the race."""
        return int(self.data.total_laps or 0)

    @property
    def drivers(self) -> List[str]:
        """Drivers that have telemetry."""
        return [d for d in self.data.drivers if d in self.telemetry]

    @property
    def detection_lines(self) -> Tuple[Optional[float], Optional[float]]:
        """``(detection_m, activation_m)``.

        Uses the FIA event note when available; otherwise falls back to the
        longest straight inferred from telemetry, and the UI labels it inferred.
        """
        d = self.event_cfg.detection_line_m
        a = self.event_cfg.activation_line_m
        if d is not None and a is not None:
            return float(d), float(a)
        if d is not None:
            return float(d), float(d) + 120.0
        ls = longest_straight(self.segments)
        if ls is None:
            return None, None
        start, end, length = ls
        gap = max(120.0, 0.10 * length)
        det = float(start + 0.35 * (end - start))
        return det, float(min(det + gap, end))

    @property
    def detection_lines_are_inferred(self) -> bool:
        """True when the lines were derived from telemetry, not the FIA note."""
        return self.event_cfg.detection_line_m is None

    # ------------------------------------------------------------------
    def team(self, driver: str) -> str:
        """Team name for a driver."""
        return self.data.driver_team(driver)

    def lap_time_s(self, driver: str, lap: int) -> Optional[float]:
        """Lap time in seconds."""
        return self.data.lap_time_s(driver, lap)

    def position_on_lap(self, driver: str, lap: int) -> Optional[int]:
        """Race position at the end of a lap (from public timing)."""
        dl = self.data.laps[
            (self.data.laps["Driver"] == driver) & (self.data.laps["LapNumber"] == lap)
        ]
        if not len(dl) or "Position" not in dl.columns:
            return None
        val = dl["Position"].iloc[0]
        return None if pd.isna(val) else int(val)

    # ------------------------------------------------------------------
    def soc_at_lap(self, driver: str, lap: int) -> float:
        """Estimated end-of-lap SoC [MJ] for a driver."""
        if self.laps_soc.empty or driver not in self.laps_soc.columns:
            return float(self.rules.soc_window_mj / 2.0)
        col = self.laps_soc[driver]
        lap = int(np.clip(lap, 1, len(col)))
        return float(col.iloc[lap - 1])

    def soc_pct_at_lap(self, driver: str, lap: int) -> float:
        """Estimated end-of-lap SoC as a percentage of the 4 MJ window."""
        return 100.0 * self.soc_at_lap(driver, lap) / self.rules.soc_window_mj

    def lap_trace(self, driver: str, lap: int) -> pd.DataFrame:
        """Within-lap estimated SoC trace for a driver on a given lap."""
        prof = self.profiles.get(driver)
        if prof is None or prof.empty:
            return pd.DataFrame()
        start = self.soc_at_lap(driver, max(lap - 1, 1)) if lap > 1 else None
        return _project_single_lap(
            prof,
            start_soc_mj=start,
            window=self.rules.soc_window_mj,
            lap=lap,
            gain=self.rules.physics["soc_feedback_gain"],
            target=self.rules.physics["soc_target_frac"],
        )

    def speed_trace(self, driver: str, lap: Optional[int] = None) -> pd.DataFrame:
        """Telemetry for one lap with clipping flags attached."""
        lap_no = lap if lap is not None else self.data.fastest_lap_number(driver)
        if lap_no is None:
            return pd.DataFrame()
        tel = get_lap_telemetry(self.data, driver, lap_no, resample_m=10.0)
        if tel.empty:
            return pd.DataFrame()
        phys = self.rules.physics
        return clipping_flags(
            tel,
            throttle_min=phys["clipping_throttle_min"],
            speed_delta_max_kph=phys["clipping_speed_delta_max_kph"],
            min_speed_kph=phys["clipping_min_speed_kph"],
            min_duration_s=phys["clipping_min_duration_s"],
        )

    # ------------------------------------------------------------------
    def timing_tower(self, lap: int) -> pd.DataFrame:
        """Timing tower for one lap: position, driver, team, estimated SoC, mode.

        Every energy column is an ESTIMATE and must be watermarked in the UI.
        """
        rows = []
        leader_time = None
        per_driver: Dict[str, Optional[float]] = {}
        for d in self.drivers:
            per_driver[d] = self.lap_time_s(d, lap)

        times = {d: t for d, t in per_driver.items() if t is not None}
        if times:
            leader_time = min(times.values())

        for d in self.drivers:
            pos = self.position_on_lap(d, lap)
            lt = per_driver.get(d)
            interval = (
                float(lt - leader_time)
                if (lt is not None and leader_time is not None)
                else None
            )
            rows.append(
                {
                    "position": pos if pos is not None else 999,
                    "driver": d,
                    "team": self.team(d),
                    "lap_time_s": lt,
                    "interval_s": interval,
                    "est_soc_mj": self.soc_at_lap(d, lap),
                    "est_soc_pct": self.soc_pct_at_lap(d, lap),
                }
            )
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df = df.sort_values("position").reset_index(drop=True)

        # mode chip: inferred ERS mode AT THE DETECTION LINE - that is the
        # moment the overtake decision is priced, so it is the mode that matters.
        det_m = self.detection_lines[0]
        modes = []
        for d in df["driver"]:
            tr = self.lap_trace(d, lap)
            if not len(tr):
                modes.append("Balance")
                continue
            if det_m is None:
                modes.append(str(tr["mode"].value_counts().idxmax()))
                continue
            i = int((tr["distance_m"] - det_m).abs().idxmin())
            modes.append(str(tr["mode"].iloc[i]))
        df["mode"] = modes
        return df

    def soc_history(self, drivers: Optional[Sequence[str]] = None) -> pd.DataFrame:
        """Wide frame: lap index -> estimated SoC [MJ] per driver."""
        if self.laps_soc.empty:
            return pd.DataFrame()
        cols = list(drivers) if drivers else list(self.laps_soc.columns)
        out = self.laps_soc[[c for c in cols if c in self.laps_soc.columns]].copy()
        out.insert(0, "lap", np.arange(1, len(out) + 1))
        return out


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------


def _aggression_from_speed(
    telemetry: Dict[str, pd.DataFrame], rules: RulesConfig
) -> Dict[str, float]:
    """Per-driver deployment multiplier from mean speed vs the field.

    A faster car is spending (or is able to spend) more energy; this is a
    relative, dimensionless nudge bounded to +/-15 % so it cannot dominate the
    rule-clamped estimate.
    """
    means = {d: float(t["Speed"].mean()) for d, t in telemetry.items() if len(t)}
    if not means:
        return {}
    med = float(np.median(list(means.values())))
    if med <= 0:
        return {d: 1.0 for d in means}
    out: Dict[str, float] = {}
    for d, m in means.items():
        rel = m / med
        # amplify gently: a 1 % speed delta is already a big F1 gap
        out[d] = float(np.clip(1.0 + (rel - 1.0) * 8.0, 0.85, 1.15))
    return out


def _project_single_lap(
    profile: pd.DataFrame,
    start_soc_mj: Optional[float],
    window: float,
    lap: int,
    gain: float = 0.35,
    target: float = 0.25,
) -> pd.DataFrame:
    """Integrate one lap's SoC from a per-segment net-energy profile.

    A proportional SoC feedback term models the real control loop: deployment is
    dialled up when the battery is full and dialled back when it is empty. Without
    it a driver whose harvest exceeds their demand would simply saturate at 4 MJ,
    which never happens in reality. It also gives the observed behaviour that a
    more aggressive driver settles at a *lower* equilibrium state of charge.
    """
    harvest = profile["harvest_mj"].to_numpy(dtype=float)
    deploy = profile["deploy_mj"].to_numpy(dtype=float)
    soc = float(window / 2.0 if start_soc_mj is None else start_soc_mj)

    socs = np.empty(len(harvest), dtype=float)
    clips = np.zeros(len(harvest), dtype=bool)
    for i in range(len(harvest)):
        g = float(np.clip(1.0 + gain * (soc / window - target) * 2.0, 0.2, 2.0))
        want = deploy[i] * g
        if want > soc + 1e-9:
            clips[i] = True
        soc = float(np.clip(soc + harvest[i] - want, 0.0, window))
        socs[i] = soc

    out = profile.copy()
    out["lap"] = lap
    out["soc_mj"] = socs
    out["soc_pct"] = 100.0 * socs / window
    out["clipping_flag"] = clips
    garr = np.clip(1.0 + gain * (socs / window - target) * 2.0, 0.2, 2.0)
    out["deploy_actual_mj"] = np.minimum(deploy * garr, socs + harvest)
    out["net_actual_mj"] = harvest - out["deploy_actual_mj"]
    out["mode"] = [
        _mode_from_row(h, d2, c)
        for h, d2, c in zip(harvest, out["deploy_actual_mj"].to_numpy(), clips)
    ]
    return out


def _mode_from_row(harvest_mj: float, deploy_mj: float, clipping: bool) -> str:
    """Render the ERS mode chip (text only - the UI uses no icons)."""
    if clipping:
        return "Deploy"
    if harvest_mj > deploy_mj and harvest_mj > 1e-6:
        return "Harvest"
    if deploy_mj > harvest_mj and deploy_mj > 1e-6:
        return "Deploy"
    return "Balance"


def build_replay(
    event: str,
    year: int = 2026,
    session: str = "R",
    rules: Optional[RulesConfig] = None,
    cache_dir: Optional[str] = None,
    drivers: Optional[Sequence[str]] = None,
    max_laps: Optional[int] = None,
) -> ReplaySession:
    """Load a cached race and estimate the SoC field.

    Parameters
    ----------
    event:
        Circuit key or FastF1 event name.
    drivers:
        Restrict to these driver codes (default: everyone with telemetry).
    max_laps:
        Cap the number of laps projected (speeds up the UI).

    Returns
    -------
    ReplaySession
    """
    rules = rules or load_rules()
    try:
        event_cfg = load_event(event)
    except Exception:
        event_cfg = EventConfig(raw={"event": event, "year": year})

    data = load_fastf1_session(year, event, session, cache_dir_=cache_dir)
    if not len(data.laps):
        raise RuntimeError(f"No lap data available for {event} {year} {session}")

    # --- segmentation: one per circuit, from a representative fast lap ----
    ref_driver = drivers[0] if drivers else None
    if ref_driver is None:
        # pick the driver with the most laps as the reference
        counts = data.laps.groupby("Driver")["LapNumber"].count()
        ref_driver = str(counts.idxmax())
    ref_tel = get_lap_telemetry(data, ref_driver, resample_m=10.0)
    if ref_tel.empty:
        ref_tel = get_lap_telemetry(data, ref_driver)
    segments = segments_from_telemetry(
        ref_tel,
        rules,
        circuit_info=data.circuit_info,
        lap_length_m=data.track_length_m,
    )
    if not segments:
        raise RuntimeError(f"Segmentation produced no segments for {event}")

    # --- per-driver representative telemetry ------------------------------
    wanted = list(drivers) if drivers else list(data.laps["Driver"].unique())
    telemetry: Dict[str, pd.DataFrame] = {}
    for d in wanted:
        tel = get_lap_telemetry(data, d, resample_m=10.0)
        if tel.empty:
            tel = get_lap_telemetry(data, d)
        if not tel.empty:
            telemetry[d] = tel

    aggression = _aggression_from_speed(telemetry, rules)

    # --- one observer lap per driver -> reusable net-energy profile -------
    profiles: Dict[str, pd.DataFrame] = {}
    for d, tel in telemetry.items():
        obs = SocObserver(rules, segments, aggression=aggression.get(d, 1.0))
        profiles[d] = obs.fit(tel)

    n_laps = int(data.total_laps or 1)
    if max_laps:
        n_laps = min(n_laps, int(max_laps))

    # --- project across the race -----------------------------------------
    window = rules.soc_window_mj
    laps_soc = pd.DataFrame(
        index=pd.RangeIndex(1, n_laps + 1, name="lap"),
        data={
            d: _project_race(
                profiles[d],
                n_laps,
                window,
                lap_mod_mj=_lap_modifiers(data, d, n_laps),
                gain=rules.physics["soc_feedback_gain"],
                target=rules.physics["soc_target_frac"],
            )
            for d in profiles
        },
    )

    return ReplaySession(
        data=data,
        rules=rules,
        event_cfg=event_cfg,
        segments=segments,
        telemetry=telemetry,
        laps_soc=laps_soc,
        profiles=profiles,
        aggression=aggression,
    )


def _project_race(
    profile: pd.DataFrame,
    n_laps: int,
    window: float,
    lap_mod_mj: Optional[np.ndarray] = None,
    gain: float = 0.35,
    target: float = 0.25,
) -> np.ndarray:
    """Project end-of-lap SoC for a whole race from one lap's profile.

    ``lap_mod_mj`` adds a per-lap correction derived from **real** lap times: a
    lap slower than the driver's own median means they were managing/lifting,
    which nets energy back into the battery. Without this the calibrated
    duty cycle would make every lap identical and the SoC trace flat.
    """
    harvest = profile["harvest_mj"].to_numpy(dtype=float)
    deploy = profile["deploy_mj"].to_numpy(dtype=float)
    soc = window / 2.0
    out = np.empty(int(n_laps), dtype=float)
    for i in range(int(n_laps)):
        g = float(np.clip(1.0 + gain * (soc / window - target) * 2.0, 0.2, 2.0))
        for h, dep in zip(harvest, deploy):
            soc = soc + h - dep * g
            if soc < 0.0:
                soc = 0.0
            elif soc > window:
                soc = window
        if lap_mod_mj is not None:
            soc = float(np.clip(soc + float(lap_mod_mj[i]), 0.0, window))
        out[i] = soc
    return out


#: MJ of energy recovered per second a driver runs slower than their own median.
PACE_TO_ENERGY_MJ_PER_S = 0.08
#: Extra recovery credited on a lap run under safety-car / VSC / yellow.
NEUTRALISED_LAP_BONUS_MJ = 0.8


def _lap_modifiers(
    data: SessionData,
    driver: str,
    n_laps: int,
) -> np.ndarray:
    """Per-lap energy correction [MJ] from real lap times and track status."""
    mod = np.zeros(int(n_laps), dtype=float)
    dl = data.laps[data.laps["Driver"] == driver]
    if not len(dl):
        return mod
    times = pd.to_numeric(
        pd.to_timedelta(dl["LapTime"], errors="coerce").dt.total_seconds(),
        errors="coerce",
    )
    dl = dl.assign(_t=times)
    valid = dl[dl["_t"].notna() & (dl["_t"] > 30)]
    if not len(valid):
        return mod
    med = float(valid["_t"].median())

    for _, row in valid.iterrows():
        lap = int(row["LapNumber"])
        if lap < 1 or lap > n_laps:
            continue
        deficit = float(row["_t"]) - med          # >0 means slower than own median
        mod[lap - 1] += float(np.clip(deficit, -2.0, 2.0)) * PACE_TO_ENERGY_MJ_PER_S
        status = str(row.get("TrackStatus", "1") or "1")
        if status not in ("1", "1.0", ""):
            mod[lap - 1] += NEUTRALISED_LAP_BONUS_MJ
    return mod


def segments_frame(replay: ReplaySession) -> pd.DataFrame:
    """Segments as a DataFrame (handy for charts and caching)."""
    return segments_to_frame(replay.segments)
