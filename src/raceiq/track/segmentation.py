"""Lap segmentation: brake / exit / straight / coast.

Geometry comes from the FastF1 circuit info (corner distances) or a bundled
TUMFTM/racetrack-database centreline when present. When neither is available the
segmentation falls back to the observed speed trace alone, which is sufficient
because braking zones are visible in public telemetry.

Reference geometry: TUMFTM/racetrack-database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from raceiq.config import RulesConfig, power_to_propel_kw
from raceiq.physics import harvest_energy_mj
from raceiq.types import Segment

__all__ = [
    "TrackGeometry",
    "build_segments",
    "segments_from_telemetry",
    "geometry_from_circuit_info",
    "mark_key_acceleration_zones",
    "longest_straight",
    "segments_to_frame",
]


@dataclass
class TrackGeometry:
    """Circuit geometry used for segmentation and the track map."""

    lap_length_m: float
    corner_distances_m: Sequence[float] = field(default_factory=list)
    x: Optional[np.ndarray] = None
    y: Optional[np.ndarray] = None
    rotation: float = 0.0
    source: str = "unknown"

    @property
    def n_corners(self) -> int:
        """Number of known corners."""
        return len(self.corner_distances_m)


def geometry_from_circuit_info(circuit_info: Dict[str, Any], lap_length_m: float) -> TrackGeometry:
    """Build :class:`TrackGeometry` from a FastF1 ``get_circuit_info()`` dict."""
    corners = circuit_info.get("corners")
    dists: List[float] = []
    xs: Optional[np.ndarray] = None
    ys: Optional[np.ndarray] = None
    if corners is not None and len(corners):
        try:
            if "Distance" in corners.columns:
                dists = [float(v) for v in corners["Distance"].tolist()]
            if {"X", "Y"} <= set(corners.columns):
                xs = corners["X"].to_numpy(dtype=float)
                ys = corners["Y"].to_numpy(dtype=float)
        except Exception:  # pragma: no cover - defensive
            pass
    return TrackGeometry(
        lap_length_m=float(lap_length_m),
        corner_distances_m=dists,
        x=xs,
        y=ys,
        rotation=float(circuit_info.get("rotation", 0.0) or 0.0),
        source="fastf1_circuit_info",
    )


def _classify(
    brake: float,
    accel_mps2: float,
    speed_kph: float,
    vmax_kph: float,
    brake_thresh: float,
) -> str:
    """Label one point of the speed trace."""
    if brake > 0 or accel_mps2 < -brake_thresh:
        return "brake"
    if accel_mps2 > 2.0:
        return "exit"
    if speed_kph >= 0.80 * max(vmax_kph, 1.0) and abs(accel_mps2) < 1.5:
        return "straight"
    return "coast"


def build_segments(
    track_geo: TrackGeometry,
    speed_trace: pd.DataFrame,
    rules: RulesConfig,
    step_m: Optional[float] = None,
) -> List[Segment]:
    """Cut a lap into fixed-length typed segments.

    Parameters
    ----------
    track_geo:
        Circuit geometry (only ``lap_length_m`` is strictly required).
    speed_trace:
        Columns ``Distance, Speed, Throttle, Brake`` (one lap).
    rules:
        Provides ``dp.segment_length_m`` and the physics block.
    step_m:
        Override the segment length.

    Returns
    -------
    list[Segment]
    """
    step = float(step_m if step_m is not None else rules.segment_length_m)
    if speed_trace is None or len(speed_trace) < 4:
        return []

    tel = speed_trace.sort_values("Distance").reset_index(drop=True)
    d = tel["Distance"].to_numpy(dtype=float)
    v = tel["Speed"].to_numpy(dtype=float)
    thr = (
        tel["Throttle"].to_numpy(dtype=float)
        if "Throttle" in tel.columns
        else np.ones_like(v)
    )
    brk = (
        tel["Brake"].to_numpy(dtype=float)
        if "Brake" in tel.columns
        else np.zeros_like(v)
    )

    d0, d1 = float(d.min()), float(d.max())
    lap_len = float(track_geo.lap_length_m) if track_geo else (d1 - d0)

    grid = np.arange(d0, d1 + step, step)
    if len(grid) < 3:  # pragma: no cover - defensive
        return []

    vg = np.interp(grid, d, v)
    tg = np.interp(grid, d, thr)
    bg = np.interp(grid, d, brk)
    # clip brake/throttle interpolation to physical range
    bg = (bg > 0.5).astype(float)
    tg = np.clip(tg, 0.0, 1.0)

    dv = np.diff(vg) * (1.0 / 3.6)
    dt = np.diff(grid) / np.maximum(vg[:-1] * (1.0 / 3.6), 1e-3)
    accel = np.concatenate([[0.0], dv / np.maximum(dt, 1e-3)])

    vmax = float(np.nanmax(vg)) if len(vg) else 0.0
    phys = rules.physics
    brake_thresh = 1.5

    segs: List[Segment] = []
    for i in range(len(grid) - 1):
        start, end = float(grid[i]), float(grid[i + 1])
        v_in, v_out = float(vg[i]), float(vg[i + 1])
        v_mean = 0.5 * (v_in + v_out)
        kind = _classify(float(bg[i]), float(accel[i]), v_mean, vmax, brake_thresh)

        harvest = 0.0
        if kind == "brake":
            harvest = harvest_energy_mj(v_in, v_out, phys)
            # never claim more than the FIA per-lap harvest cap allows
            harvest = min(harvest, rules.harvest_cap_mj_per_lap)

        segs.append(
            Segment(
                index=i,
                start_m=start,
                end_m=end,
                kind=kind,
                mean_speed_kph=v_mean,
                entry_speed_kph=v_in,
                exit_speed_kph=v_out,
                is_key_acceleration=False,
                harvest_potential_mj=float(harvest),
            )
        )

    segs = mark_key_acceleration_zones(segs, n_zones=2, min_length_m=250.0)
    _ = lap_len  # retained for clarity / future geometry alignment
    return segs


def mark_key_acceleration_zones(
    segments: List[Segment],
    n_zones: int = 2,
    min_length_m: float = 250.0,
    kinds: Sequence[str] = ("straight", "exit"),
) -> List[Segment]:
    """Flag the longest full-throttle acceleration runs as key zones (350 kW).

    The per-event FIA note designates these zones explicitly; when the note is
    unavailable they are **inferred** as the longest full-throttle acceleration
    runs and the UI must label them as inferred.

    A run is any contiguous stretch of acceleration segments. Corner exits are
    included because that is where a car is flat out and still accelerating -
    restricting this to segments labelled ``straight`` fragments a real straight
    into pieces too short to clear any sensible length threshold.
    """
    if not segments:
        return segments

    runs: List[List[int]] = []
    cur: List[int] = []
    for s in segments:
        if s.kind in kinds:
            cur.append(s.index)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)

    lengths = []
    for r in runs:
        length = sum(segments[i].length_m for i in r)
        lengths.append((length, r))
    lengths.sort(key=lambda t: -t[0])

    out = list(segments)
    for length, r in lengths[:n_zones]:
        if length < min_length_m:
            continue
        for i in r:
            s = segments[i]
            out[i] = Segment(
                index=s.index, start_m=s.start_m, end_m=s.end_m, kind=s.kind,
                mean_speed_kph=s.mean_speed_kph, entry_speed_kph=s.entry_speed_kph,
                exit_speed_kph=s.exit_speed_kph, is_key_acceleration=True,
                harvest_potential_mj=s.harvest_potential_mj,
            )
    return out


def longest_straight(segments: Sequence[Segment]) -> Optional[tuple]:
    """Return ``(start_m, end_m, length_m)`` of the longest straight run."""
    best = None
    cur_start = None
    cur_end = None
    for s in list(segments) + [None]:  # type: ignore[list-item]
        if s is not None and s.kind == "straight":
            if cur_start is None:
                cur_start = s.start_m
            cur_end = s.end_m
            continue
        if cur_start is not None and cur_end is not None:
            length = cur_end - cur_start
            if best is None or length > best[2]:
                best = (cur_start, cur_end, length)
        cur_start = cur_end = None
    return best


def segments_from_telemetry(
    telemetry: pd.DataFrame,
    rules: RulesConfig,
    circuit_info: Optional[Dict[str, Any]] = None,
    lap_length_m: Optional[float] = None,
) -> List[Segment]:
    """Convenience wrapper: telemetry -> segments."""
    if telemetry is None or len(telemetry) < 4:
        return []
    if lap_length_m is None:
        lap_length_m = float(telemetry["Distance"].max() - telemetry["Distance"].min())
    geo = (
        geometry_from_circuit_info(circuit_info or {}, lap_length_m)
        if circuit_info
        else TrackGeometry(lap_length_m=lap_length_m, source="speed_trace")
    )
    return build_segments(geo, telemetry, rules)


def segments_to_frame(segments: Sequence[Segment]) -> pd.DataFrame:
    """Segments -> tidy DataFrame (for caching and charts)."""
    return pd.DataFrame(
        [
            {
                "index": s.index,
                "start_m": s.start_m,
                "end_m": s.end_m,
                "length_m": s.length_m,
                "kind": s.kind,
                "mean_speed_kph": s.mean_speed_kph,
                "entry_speed_kph": s.entry_speed_kph,
                "exit_speed_kph": s.exit_speed_kph,
                "is_key_acceleration": s.is_key_acceleration,
                "harvest_potential_mj": s.harvest_potential_mj,
                "duration_s": s.duration_s,
            }
            for s in segments
        ]
    )


def max_legal_deploy_kw(speed_kph: float, segment: Segment, rules: RulesConfig) -> float:
    """Highest MGU-K power the rulebook permits in this segment [kW].

    ``min(350, power_to_propel(v), zone cap, base + boost cap)``.
    """
    zone = rules.zone_deploy_kw["key_acceleration" if segment.is_key_acceleration else "other"]
    return min(
        rules.mgu_k_max_kw,
        power_to_propel_kw(speed_kph, rules),
        zone,
        rules.base_deploy_kw + rules.race_boost_cap_kw,
    )
