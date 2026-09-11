"""Deterministic SoC observer.

**No model is trained here.** There is no ground-truth battery label in public
data, so state of charge is *reconstructed* by integrating an energy balance
that is clamped by the FIA rulebook:

* harvest  - brake energy in braking segments, capped by Art. 5.4.9 (9 MJ/lap),
  by the recoverable brake energy and by the headroom in the 4 MJ window;
* deploy   - full legal MGU-K power in deploy-eligible segments, capped by
  Art. 5.4.1 (350 kW), the Art. 5.4.5 power-to-propel rampdown, the per-zone cap
  and the post-Miami boost cap;
* closure  - the deployment duty cycle is calibrated so that a lap is
  energy-neutral (deploy == harvest). Without this the battery would simply
  saturate or empty, which real cars never do.

When the battery cannot serve the demanded deployment the car **clips** - and
clipping is observable in public telemetry, which is how we validate the
estimate (see :mod:`raceiq.inference.clipping`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from raceiq.config import RulesConfig
from raceiq.inference.clipping import clipping_flags
from raceiq.inference.ers_mode import ErsClassifier
from raceiq.physics import superclip_penalty_s
from raceiq.track.segmentation import max_legal_deploy_kw
from raceiq.types import Segment, SocState

__all__ = ["SocObserver", "LapObservation", "observe_field"]


@dataclass
class LapObservation:
    """Result of running the observer over one lap."""

    driver: str
    lap: int
    frame: pd.DataFrame
    summary: Dict[str, Any] = field(default_factory=dict)

    @property
    def soc_series(self) -> pd.Series:
        """Estimated SoC per segment [MJ]."""
        return self.frame["soc_mj"]

    @property
    def clipping_count(self) -> int:
        """Number of clipping samples detected in the lap."""
        return int(self.frame["clipping_flag"].sum())

    def mode_counts(self) -> Dict[str, int]:
        """Count of samples in each ERS mode."""
        return self.frame["mode"].value_counts().to_dict()


class SocObserver:
    """Rule-clamped energy-balance observer for one car.

    Parameters
    ----------
    rules:
        Loaded ``rules_2026.json``.
    segments:
        Lap segmentation for the circuit.
    initial_soc_mj:
        Starting charge; defaults to the middle of the window.
    aggression:
        Per-driver multiplier on the calibrated deployment duty (1.0 = field
        average). Derived from the driver's mean speed relative to the field.
    """

    def __init__(
        self,
        rules: RulesConfig,
        segments: Sequence[Segment],
        initial_soc_mj: Optional[float] = None,
        aggression: float = 1.0,
    ) -> None:
        self.rules = rules
        self.segments: List[Segment] = list(segments)
        self.window = rules.soc_window_mj
        self.physics = rules.physics
        self.aggression = float(aggression)
        self.initial_soc = float(
            self.window / 2.0 if initial_soc_mj is None else initial_soc_mj
        )
        self.classifier = ErsClassifier(soc_window_mj=self.window)
        self.deploy_weight: Dict[str, float] = {
            k: float(v) for k, v in rules.dp.get("deploy_weight_by_kind", {}).items()
            if not k.startswith("_")
        } or {"straight": 1.0, "exit": 0.45, "coast": 0.15, "brake": 0.0}

        self.soc_mj = self.initial_soc
        self.lap_harvested = 0.0
        self.lap_deployed = 0.0
        self.superclipped_mj = 0.0

        # Two different quantities that used to be conflated (see
        # ``_calibrate_duty``). The *sustainable* duty is an energy budget; the
        # demand duty is what the driver actually asks for.
        self.sustainable_duty = self._calibrate_duty()
        self.duty = float(np.clip(self.aggression, 0.0, 1.0))

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------
    def _eligible(self, seg: Segment) -> bool:
        """A segment can accept deployment (straight or corner exit)."""
        return seg.kind in ("straight", "exit")

    def _segment_capacity_mj(self, seg: Segment) -> float:
        """Energy that would be spent deploying flat out through a segment."""
        p = max_legal_deploy_kw(seg.mean_speed_kph, seg, self.rules)
        return p * seg.duration_s / 1000.0

    def _calibrate_duty(self) -> float:
        """Duty cycle that makes the lap energy-neutral, clipped to [0, 1].

        Harvest is what the circuit gives back (brake energy, capped at 9 MJ/lap);
        deployment is scaled to match it. This is why the same car attacks more at
        Baku (~7.1 MJ) and harvests more at Monza (~3.3 MJ).

        IMPORTANT - this is a *budget*, not a demand. It is exposed as
        :attr:`sustainable_duty` and is what the planner should use. It must NOT
        be used to scale what the driver asks for in :meth:`update`: a driver who
        only ever asks for what they can afford can, by construction, never be
        denied - and "wanted more than the battery could give" is precisely what
        clipping means. Scaling demand by the sustainable duty made the observer
        structurally incapable of predicting clipping (it predicted 0.00% on
        36/36 real Melbourne laps where ~6.3% is observed).
        """
        harvest_total = min(
            sum(s.harvest_potential_mj for s in self.segments),
            self.rules.harvest_cap_mj_per_lap,
        )
        deploy_capacity = sum(
            self._segment_capacity_mj(s) for s in self.segments if self._eligible(s)
        )
        if deploy_capacity <= 1e-9:
            return 0.0
        duty = harvest_total / deploy_capacity
        return float(np.clip(duty * self.aggression, 0.0, 1.0))

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def reset(self, soc_mj: Optional[float] = None) -> None:
        """Reset the observer to the start of a lap."""
        self.soc_mj = float(self.initial_soc if soc_mj is None else soc_mj)
        self.soc_mj = float(np.clip(self.soc_mj, 0.0, self.window))
        self.lap_harvested = 0.0
        self.lap_deployed = 0.0
        self.superclipped_mj = 0.0

    @property
    def soc_pct(self) -> float:
        """State of charge as a percentage of the 4 MJ usable window."""
        return 100.0 * self.soc_mj / self.window

    # ------------------------------------------------------------------
    # Single-sample update (spec signature)
    # ------------------------------------------------------------------
    def update(self, telemetry_row: Any, segment: Segment) -> SocState:
        """Advance the observer by one telemetry sample.

        Parameters
        ----------
        telemetry_row:
            Mapping/Series with ``Speed``, ``Throttle``, ``Brake`` and optionally
            ``Distance``.
        segment:
            The :class:`~raceiq.types.Segment` this sample falls in.

        Returns
        -------
        SocState
            Estimated SoC (MJ and %), inferred ERS mode and clipping flag.
        """
        speed = float(_get(telemetry_row, "Speed", segment.mean_speed_kph))
        throttle = float(_get(telemetry_row, "Throttle", 1.0))
        brake = float(_get(telemetry_row, "Brake", 0.0))
        distance = float(_get(telemetry_row, "Distance", segment.start_m))

        harvested = 0.0
        deployed = 0.0
        clipping = False
        superclipping = False

        # --- Harvest ---------------------------------------------------
        if brake > 0.0 or segment.kind == "brake":
            # A segment typed 'brake' already decelerated in the real trace, so
            # its full (already efficiency-derated) potential is available.
            potential = segment.harvest_potential_mj
            headroom = self.window - self.soc_mj
            cap_left = self.rules.harvest_cap_mj_per_lap - self.lap_harvested
            harvested = max(0.0, min(potential, headroom, cap_left))
            self.soc_mj += harvested
            self.lap_harvested += harvested

        # --- Deploy ----------------------------------------------------
        elif self._eligible(segment) and throttle >= 0.5:
            p_max = max_legal_deploy_kw(speed, segment, self.rules)
            p_req = p_max * self.duty * throttle
            dt = segment.duration_s
            want_mj = p_req * dt / 1000.0
            have_mj = self.soc_mj
            deployed = min(want_mj, have_mj)
            self.soc_mj -= deployed
            self.lap_deployed += deployed
            # wanted more than the battery could give, at full throttle => clipping
            if throttle >= self.physics["clipping_throttle_min"] and want_mj - deployed > 1e-6:
                clipping = True

            # --- Superclipping: empty battery, flat out, recharge off the ICE
            if (
                self.soc_mj < 0.05
                and throttle >= self.physics["clipping_throttle_min"]
                and segment.kind == "straight"
                and self.lap_harvested < self.rules.harvest_cap_mj_per_lap
            ):
                p_sc = min(self.rules.superclip_max_kw, p_max)
                e_sc = p_sc * dt / 1000.0
                headroom = self.window - self.soc_mj
                cap_left = self.rules.harvest_cap_mj_per_lap - self.lap_harvested
                e_sc = max(0.0, min(e_sc, headroom, cap_left))
                self.soc_mj += e_sc
                self.lap_harvested += e_sc
                self.superclipped_mj += e_sc
                harvested += e_sc
                superclipping = True
                clipping = True

        # --- Clamp -----------------------------------------------------
        self.soc_mj = float(np.clip(self.soc_mj, 0.0, self.window))

        mode = self.classifier.classify(
            SocState(
                soc_mj=self.soc_mj,
                mode="Balance",
                clipping_flag=clipping,
                soc_pct=self.soc_pct,
            ),
            throttle=throttle,
            brake=brake,
            speed_kph=speed,
        )

        return SocState(
            soc_mj=self.soc_mj,
            mode=mode,
            clipping_flag=bool(clipping),
            harvested_mj=harvested,
            deployed_mj=deployed,
            soc_pct=self.soc_pct,
            distance_m=distance,
        )

    # ------------------------------------------------------------------
    # Batch: one full lap
    # ------------------------------------------------------------------
    def run_lap(
        self,
        telemetry: pd.DataFrame,
        driver: str = "",
        lap: int = 0,
        start_soc_mj: Optional[float] = None,
    ) -> LapObservation:
        """Integrate the observer over a whole lap.

        Parameters
        ----------
        telemetry:
            One lap of ``Distance, Speed, Throttle, Brake``.
        driver, lap:
            Labels recorded on the output.
        start_soc_mj:
            Charge at the start of the lap; defaults to the observer's state.

        Returns
        -------
        LapObservation
        """
        self.reset(start_soc_mj)
        if telemetry is None or len(telemetry) == 0 or not self.segments:
            return LapObservation(driver=driver, lap=lap, frame=pd.DataFrame())

        tel = telemetry.sort_values("Distance").reset_index(drop=True)
        dist = tel["Distance"].to_numpy(dtype=float)
        speed = tel["Speed"].to_numpy(dtype=float)
        thr = tel["Throttle"].to_numpy(dtype=float)
        if thr.max() > 1.5:
            thr = thr / 100.0
        brk = (
            tel["Brake"].to_numpy(dtype=float)
            if "Brake" in tel.columns
            else np.zeros_like(speed)
        )

        rows: List[Dict[str, Any]] = []
        seg_speed: List[float] = []
        seg_thr: List[float] = []
        for seg in self.segments:
            mid = 0.5 * (seg.start_m + seg.end_m)
            i = int(np.clip(np.searchsorted(dist, mid), 0, len(dist) - 1))
            row = {
                "Speed": float(speed[i]),
                "Throttle": float(thr[i]),
                "Brake": float(brk[i]),
                "Distance": mid,
            }
            # Keep the sampled values so the observable-clipping mask below is
            # aligned with the frame (one row per segment, not per telemetry row).
            seg_speed.append(float(speed[i]))
            seg_thr.append(float(thr[i]))
            st = self.update(row, seg)
            rows.append(
                {
                    "segment": seg.index,
                    "distance_m": mid,
                    "kind": seg.kind,
                    "speed_kph": row["Speed"],
                    "throttle": row["Throttle"],
                    "brake": row["Brake"],
                    "soc_mj": st.soc_mj,
                    "soc_pct": st.soc_pct,
                    "mode": st.mode,
                    "clipping_flag": st.clipping_flag,
                    "harvested_mj": st.harvested_mj,
                    "deployed_mj": st.deployed_mj,
                    "is_key_acceleration": seg.is_key_acceleration,
                }
            )

        frame = pd.DataFrame(rows)

        # Cross-check against the independent clipping detector on real telemetry.
        flagged = clipping_flags(
            tel,
            throttle_min=self.physics["clipping_throttle_min"],
            speed_delta_max_kph=self.physics["clipping_speed_delta_max_kph"],
            min_speed_kph=self.physics["clipping_min_speed_kph"],
            min_duration_s=self.physics["clipping_min_duration_s"],
            min_speed_frac_of_max=self.physics["clipping_min_speed_frac_of_max"],
        )
        observed_clip_frac = (
            float(flagged["clipping"].mean()) if len(flagged) else 0.0
        )

        # Like-for-like comparison with the detector.
        #
        # ``predicted_clip_frac`` counts every sample where the driver wanted
        # more than the battery could give - but most of those are invisible in
        # telemetry, because the ICE alone still accelerates the car. The
        # detector can only ever see clipping where the car is flat out AND near
        # the top of its speed range, so to compare like with like we restrict
        # the prediction to exactly that regime (using only throttle and speed -
        # never the detector's own flatness test, which would be circular).
        observable = _observable_clipping_mask(
            pd.DataFrame({"Speed": seg_speed, "Throttle": seg_thr}),
            throttle_min=self.physics["clipping_throttle_min"],
            min_speed_frac_of_max=self.physics["clipping_min_speed_frac_of_max"],
        )
        if len(observable) == len(frame) and len(frame):
            pred_observable = float(
                (frame["clipping_flag"].to_numpy() & observable).sum()
            ) / float(max(1, int(observable.sum())))
        else:
            pred_observable = 0.0

        summary = {
            "driver": driver,
            "lap": lap,
            "duty": self.duty,
            "sustainable_duty": self.sustainable_duty,
            "aggression": self.aggression,
            "harvest_mj": self.lap_harvested,
            "deploy_mj": self.lap_deployed,
            "superclip_mj": self.superclipped_mj,
            "net_mj": self.lap_deployed - self.lap_harvested,
            "end_soc_mj": self.soc_mj,
            "end_soc_pct": self.soc_pct,
            "soc_min_mj": float(frame["soc_mj"].min()) if len(frame) else 0.0,
            "soc_max_mj": float(frame["soc_mj"].max()) if len(frame) else 0.0,
            "predicted_clip_frac": float(frame["clipping_flag"].mean()) if len(frame) else 0.0,
            "predicted_observable_clip_frac": pred_observable,
            "observed_clip_frac": observed_clip_frac,
            "n_clipping_samples": int(frame["clipping_flag"].sum()) if len(frame) else 0,
        }
        return LapObservation(driver=driver, lap=lap, frame=frame, summary=summary)


    # ------------------------------------------------------------------
    # Reusable per-lap net-energy profile
    # ------------------------------------------------------------------
    def fit(self, telemetry: pd.DataFrame) -> pd.DataFrame:
        """Calibrate the deployment duty against real telemetry, then profile.

        Pass 1 profiles the lap at full deployment to measure the *actual*
        harvest the circuit returns and the deployment the car would use. Pass 2
        re-profiles with ``duty = harvest / deploy_capacity`` so the lap closes
        in energy balance - which is why the estimate never saturates or empties.

        The energy-balanced value is stored on :attr:`sustainable_duty`. It is
        deliberately NOT written to :attr:`duty`, which stays the driver's
        *demand* level - otherwise profiling would silently disable clipping
        detection for everything that runs afterwards.
        """
        first = self.lap_profile(telemetry, duty=1.0)
        if first.empty:
            return first
        harvest = float(first["harvest_mj"].sum())
        capacity = float(first["deploy_mj"].sum())
        if capacity <= 1e-9:
            self.sustainable_duty = 0.0
            return first
        self.sustainable_duty = float(
            np.clip(harvest / capacity * self.aggression, 0.0, 1.0)
        )
        return self.lap_profile(telemetry, duty=self.sustainable_duty)

    def fit_duty_to_observed(
        self,
        telemetry: pd.DataFrame,
        target: Optional[float] = None,
        tol: float = 0.0025,
        max_iter: int = 20,
    ) -> Dict[str, float]:
        """Calibrate the *demand* duty against clipping that is actually visible.

        This is the observable-based calibration the spec asks for (Section 7):
        the FIA publishes no SoC channel, but deployment clipping **is** visible
        in public telemetry. The demand duty is the one free parameter that
        controls how hard the driver is asking, so we bisect it until the
        observer reproduces the clipping rate the independent detector measures.

        ``predicted_observable_clip_frac`` is monotonic in the duty, so a plain
        bisection converges.

        Returns
        -------
        dict
            ``duty`` (fitted), ``target`` (observed rate), ``achieved``
            (predicted observable rate at the fitted duty) and ``abs_error``.
        """
        if telemetry is None or len(telemetry) < 4:
            return {"duty": self.duty, "target": 0.0, "achieved": 0.0, "abs_error": 0.0}

        if target is None:
            flagged = clipping_flags(
                telemetry,
                throttle_min=self.physics["clipping_throttle_min"],
                speed_delta_max_kph=self.physics["clipping_speed_delta_max_kph"],
                min_speed_kph=self.physics["clipping_min_speed_kph"],
                min_duration_s=self.physics["clipping_min_duration_s"],
                min_speed_frac_of_max=self.physics["clipping_min_speed_frac_of_max"],
            )
            target = float(flagged["clipping"].mean()) if len(flagged) else 0.0

        original = self.duty
        lo, hi = 0.0, 1.0
        best_duty, best_err, best_val = float(self.duty), float("inf"), 0.0
        for _ in range(int(max_iter)):
            mid = 0.5 * (lo + hi)
            self.duty = mid
            achieved = float(
                self.run_lap(telemetry).summary["predicted_observable_clip_frac"]
            )
            err = abs(achieved - target)
            if err < best_err:
                best_duty, best_err, best_val = mid, err, achieved
            if best_err <= tol:
                break
            if achieved > target:
                hi = mid
            else:
                lo = mid

        self.duty = best_duty
        return {
            "duty": float(best_duty),
            "target": float(target),
            "achieved": float(best_val),
            "abs_error": float(best_err),
            "previous_duty": float(original),
        }

    def lap_profile(
        self, telemetry: pd.DataFrame, duty: Optional[float] = None
    ) -> pd.DataFrame:
        """Per-segment harvest / deploy demand for one representative lap.

        The profile is the *demand*, computed without a state-of-charge gate, so
        it can be replayed cheaply across a whole race: the projection re-clamps
        into the 4 MJ window and raises the clipping flag whenever the demand
        exceeds what is on board.

        Returns
        -------
        pandas.DataFrame
            ``segment, distance_m, kind, speed_kph, throttle, brake,
            harvest_mj, deploy_mj, net_mj, duration_s, is_key_acceleration``
        """
        if telemetry is None or len(telemetry) == 0 or not self.segments:
            return pd.DataFrame()

        tel = telemetry.sort_values("Distance").reset_index(drop=True)
        dist = tel["Distance"].to_numpy(dtype=float)
        speed = tel["Speed"].to_numpy(dtype=float)
        thr = tel["Throttle"].to_numpy(dtype=float)
        if thr.max() > 1.5:
            thr = thr / 100.0
        brk = (
            tel["Brake"].to_numpy(dtype=float)
            if "Brake" in tel.columns
            else np.zeros_like(speed)
        )

        rows: List[Dict[str, Any]] = []
        lap_harvest = 0.0
        for seg in self.segments:
            mid = 0.5 * (seg.start_m + seg.end_m)
            i = int(np.clip(np.searchsorted(dist, mid), 0, len(dist) - 1))
            v, t, b = float(speed[i]), float(thr[i]), float(brk[i])

            harvest = 0.0
            if b > 0.0 or seg.kind == "brake":
                cap_left = max(0.0, self.rules.harvest_cap_mj_per_lap - lap_harvest)
                harvest = max(0.0, min(seg.harvest_potential_mj, cap_left))
                lap_harvest += harvest

            deploy = 0.0
            if self._eligible(seg) and t >= 0.5:
                w = float(self.deploy_weight.get(seg.kind, 0.0))
                d = self.duty if duty is None else duty
                p = max_legal_deploy_kw(v, seg, self.rules) * d * t * w
                deploy = p * seg.duration_s / 1000.0

            rows.append(
                {
                    "segment": seg.index,
                    "distance_m": mid,
                    "kind": seg.kind,
                    "speed_kph": v,
                    "throttle": t,
                    "brake": b,
                    "harvest_mj": harvest,
                    "deploy_mj": deploy,
                    "net_mj": harvest - deploy,
                    "duration_s": seg.duration_s,
                    "is_key_acceleration": seg.is_key_acceleration,
                }
            )
        return pd.DataFrame(rows)


def _observable_clipping_mask(
    telemetry: pd.DataFrame,
    throttle_min: float = 0.98,
    min_speed_frac_of_max: float = 0.90,
) -> np.ndarray:
    """Samples where clipping would be *visible* in public telemetry.

    The detector in :mod:`raceiq.inference.clipping` requires high throttle and
    a speed near the lap maximum. This reproduces only that *regime* - from
    throttle and speed alone - so the observer can be compared against the
    detector without circularity (no flatness test here).
    """
    if telemetry is None or len(telemetry) == 0:
        return np.zeros(0, dtype=bool)
    speed = telemetry["Speed"].to_numpy(dtype=float)
    thr = telemetry["Throttle"].to_numpy(dtype=float)
    if thr.max() > 1.5:  # FastF1 returns 0-100
        thr = thr / 100.0
    vmax = float(np.nanmax(speed))
    return (thr >= throttle_min) & (speed >= min_speed_frac_of_max * vmax)


def _get(row: Any, key: str, default: float) -> float:
    """Read a value from a dict, Series or object without raising."""
    try:
        if isinstance(row, dict):
            v = row.get(key, default)
        elif hasattr(row, key):
            v = getattr(row, key)
        else:  # pandas Series
            v = row[key]
    except Exception:  # pragma: no cover - defensive
        return float(default)
    try:
        v = float(v)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return float(default)
    return default if not np.isfinite(v) else v


def observe_field(
    telemetry_by_driver: Dict[str, pd.DataFrame],
    segments: Sequence[Segment],
    rules: RulesConfig,
    aggression: Optional[Dict[str, float]] = None,
    lap: int = 0,
) -> Dict[str, LapObservation]:
    """Run the observer for every car (cheap: ~22 x 500 arithmetic segments).

    Parameters
    ----------
    telemetry_by_driver:
        Driver code -> one representative lap of telemetry.
    segments:
        Circuit segmentation (built once).
    aggression:
        Optional per-driver duty multiplier.

    Returns
    -------
    dict[str, LapObservation]
    """
    out: Dict[str, LapObservation] = {}
    for drv, tel in telemetry_by_driver.items():
        agg = float((aggression or {}).get(drv, 1.0))
        obs = SocObserver(rules, segments, aggression=agg)
        out[drv] = obs.run_lap(tel, driver=drv, lap=lap)
    return out
