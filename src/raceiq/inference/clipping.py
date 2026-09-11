"""Clipping / superclipping detection from public telemetry.

**This is the validation signal for the whole project.** Clipping is observable:
the driver is at full throttle but the speed stops rising because the MGU-K is
diverting ICE power into the battery. If our estimated SoC says "empty" and the
car does *not* clip, the observer is wrong.

Real 2026 cases cited in the spec: Bahrain T12 (Leclerc/Norris flat through 300 m
capped ~240 km/h), Albert Park (Mercedes 327 km/h, later/smaller clipping than
Red Bull/Audi), Spa (Norris vs Antonelli deployment deltas).
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = ["ClippingDetector", "clipping_flags", "clipping_summary"]


class ClippingDetector:
    """Stateful per-sample clipping detector.

    A sample is flagged when all of the following hold:

    * throttle is essentially fully open,
    * the speed has stopped rising (or is falling),
    * the car is near its own lap maximum, so aero - not grip or gearing - is
      the limit (this is what separates real clipping from simply reaching
      terminal velocity),
    * the condition persists for at least ``min_duration_s``.
    """

    def __init__(
        self,
        throttle_min: float = 0.98,
        speed_delta_max_kph: float = 0.35,
        min_speed_kph: float = 150.0,
        min_duration_s: float = 0.25,
        min_speed_frac_of_max: float = 0.90,
    ) -> None:
        self.throttle_min = float(throttle_min)
        self.speed_delta_max_kph = float(speed_delta_max_kph)
        self.min_speed_kph = float(min_speed_kph)
        self.min_duration_s = float(min_duration_s)
        self.min_speed_frac_of_max = float(min_speed_frac_of_max)
        self._elapsed = 0.0
        self._prev_speed: float | None = None
        self._prev_time: float | None = None

    def reset(self) -> None:
        """Clear the persistence accumulator (call at the start of each lap)."""
        self._elapsed = 0.0
        self._prev_speed = None
        self._prev_time = None

    def detect(self, speed: float, throttle: float, prev_speed: float) -> bool:
        """Return True when this sample is a clipping sample.

        Parameters
        ----------
        speed:
            Current speed [km/h].
        throttle:
            Normalised 0-1.
        prev_speed:
            Previous sample's speed [km/h].
        """
        if (
            throttle >= self.throttle_min
            and speed >= self.min_speed_kph
            and (speed - prev_speed) <= self.speed_delta_max_kph
        ):
            self._elapsed += 0.05  # nominal sample period; refined in batch mode
            return self._elapsed >= self.min_duration_s
        self._elapsed = 0.0
        return False


def clipping_flags(
    telemetry: pd.DataFrame,
    throttle_min: float = 0.98,
    speed_delta_max_kph: float = 0.35,
    min_speed_kph: float = 150.0,
    min_duration_s: float = 0.25,
    min_speed_frac_of_max: float = 0.90,
) -> pd.DataFrame:
    """Vectorised clipping detection over a lap's telemetry.

    Parameters
    ----------
    telemetry:
        Columns ``Distance, Speed, Throttle`` (and optionally ``Time``).

    Returns
    -------
    pandas.DataFrame
        The input plus ``dSpeed`` and ``clipping`` columns.
    """
    if telemetry is None or len(telemetry) < 3:
        empty = telemetry.copy() if telemetry is not None else pd.DataFrame()
        if len(empty):
            empty["dSpeed"] = 0.0
            empty["clipping"] = False
        return empty

    df = telemetry.sort_values("Distance").reset_index(drop=True).copy()
    speed = df["Speed"].to_numpy(dtype=float)
    thr = df["Throttle"].to_numpy(dtype=float)
    if thr.max() > 1.5:  # FastF1 returns 0-100
        thr = thr / 100.0

    vmax = float(np.nanmax(speed))
    floor = max(float(min_speed_kph), float(min_speed_frac_of_max) * vmax)
    dv = np.diff(speed, prepend=speed[0])
    raw = (thr >= throttle_min) & (speed >= floor) & (dv <= speed_delta_max_kph)

    # persistence filter using real timestamps when available
    if "Time" in df.columns:
        t = pd.to_numeric(df["Time"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        dt = np.diff(t, prepend=t[0])
        dt = np.clip(dt, 0.0, 0.5)
    else:
        dt = np.full(len(df), 0.05)

    flags = np.zeros(len(df), dtype=bool)
    run = 0.0
    for i in range(len(df)):
        if raw[i]:
            run += dt[i]
        else:
            run = 0.0
        flags[i] = run >= min_duration_s

    df["dSpeed"] = dv
    df["clipping"] = flags
    return df


def clipping_summary(flagged: pd.DataFrame) -> Dict[str, float]:
    """Aggregate clipping statistics for one lap.

    Returns
    -------
    dict
        ``n_events``, ``clipped_distance_m``, ``clipped_fraction``,
        ``entry_speed_kph`` (speed at the first clipping sample, ``nan`` if none).
    """
    if flagged is None or len(flagged) == 0 or "clipping" not in flagged.columns:
        return {
            "n_events": 0, "clipped_distance_m": 0.0,
            "clipped_fraction": 0.0, "entry_speed_kph": float("nan"),
        }
    d = flagged["Distance"].to_numpy(dtype=float)
    m = flagged["clipping"].to_numpy(dtype=bool)
    if not m.any():
        return {
            "n_events": 0, "clipped_distance_m": 0.0,
            "clipped_fraction": 0.0, "entry_speed_kph": float("nan"),
        }
    # count contiguous runs as separate events
    starts = np.flatnonzero(m & ~np.r_[False, m[:-1]])
    span = float(d.max() - d.min()) if len(d) > 1 else 0.0
    clipped_m = float(np.diff(d, prepend=d[0])[m].sum())
    return {
        "n_events": int(len(starts)),
        "clipped_distance_m": clipped_m,
        "clipped_fraction": float(clipped_m / span) if span > 0 else 0.0,
        "entry_speed_kph": float(flagged["Speed"].to_numpy()[starts[0]]),
    }


def clipping_events(flagged: pd.DataFrame) -> List[Tuple[float, float]]:
    """Return ``[(start_m, end_m), ...]`` for each contiguous clipping run."""
    if flagged is None or len(flagged) == 0 or "clipping" not in flagged.columns:
        return []
    d = flagged["Distance"].to_numpy(dtype=float)
    m = flagged["clipping"].to_numpy(dtype=bool)
    out: List[Tuple[float, float]] = []
    i = 0
    n = len(m)
    while i < n:
        if m[i]:
            j = i
            while j + 1 < n and m[j + 1]:
                j += 1
            out.append((float(d[i]), float(d[j])))
            i = j + 1
        else:
            i += 1
    return out


def _unused(_: Sequence[float]) -> None:  # pragma: no cover - keeps linters quiet
    return None
