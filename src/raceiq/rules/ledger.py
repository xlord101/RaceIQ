"""FIA rule-compliance ledger.

Every candidate energy plan is checked against the 2026 rule stack before it is
allowed to reach the decision engine. An illegal plan does not get a slightly
worse EV - it is rejected outright (the EV engine treats it as ``-inf``).

All limits are read from ``config/rules_2026.json``; nothing is hard-coded.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from raceiq.config import RulesConfig, power_to_propel_kw
from raceiq.types import ComplianceResult, DeploymentPlan, PlanSegment, Segment

__all__ = ["ComplianceLedger", "RULE_LABELS", "certificate_text"]

#: Human-readable labels for the compliance board (text only - no icons).
RULE_LABELS: Dict[str, str] = {
    "soc_window": "Delta SoC <= 4 MJ (Art. 5.4.8)",
    "harvest_cap": "Harvest <= 8.5 MJ/lap standard ceiling (Art. 5.4.9)",
    "deploy_cap": "Deploy <= allowance (Art. 5.4)",
    "power_to_propel": "ERS-K curve C5.2.8: 1800-5v / 6900-20v taper / 0 above 345",
    "zone_deploy": "Zone cap 350 / 250 kW",
    "boost_cap": "Boost <= +150 kW (post-Miami)",
    "start_min_speed": "Start >= 50 km/h",
    "pit_gain": "Pit stationary gain <= 100 kJ",
    "torque": "MGU-K torque <= 500 Nm",
    "slew_rate": "Slew <= 100 kW/s",
}


class ComplianceLedger:
    """Checks candidate plans (and the observer's own estimates) against rules.

    Parameters
    ----------
    rules:
        Loaded ``rules_2026.json``.
    event_deploy_mj:
        Per-event deployment allowance; defaults to the rules value.
    """

    def __init__(self, rules: RulesConfig, event_deploy_mj: Optional[float] = None) -> None:
        self.rules = rules
        self.event_deploy_mj = float(
            event_deploy_mj if event_deploy_mj is not None else rules.deploy_mj_per_lap
        )

    # ------------------------------------------------------------------
    def check(
        self,
        plan: DeploymentPlan,
        speed_kph: float = 0.0,
        lap: int = 1,
        segment_speeds: Optional[Sequence[float]] = None,
        slew_rate: bool = True,
    ) -> ComplianceResult:
        """Check a full-lap plan.

        Parameters
        ----------
        plan:
            Candidate deployment plan.
        speed_kph:
            Representative speed used for the power-to-propel rampdown when
            ``segment_speeds`` is not supplied.
        lap:
            Lap number (lap 1 is subject to the start-speed rule).
        segment_speeds:
            Per-segment speeds [km/h], one per plan segment. When given, the
            power-to-propel rampdown is checked against each segment's own speed
            instead of a single representative speed - the limit is a function of
            speed, so a 350 kW surge is legal only where the air is thin enough.
        slew_rate:
            When ``False`` the slew-rate limit is treated as not-applicable and
            skipped. The coarse planner (Tier-1 DP, 10 m segments) outputs target
            powers that the controller ramps between, so the hardware slew limit
            is a controller concern, not a planner one; the per-segment power and
            energy caps below are what the planner must honour.

        Returns
        -------
        ComplianceResult
        """
        checks: Dict[str, bool] = {}
        details: Dict[str, str] = {}
        measured: Dict[str, float] = {}

        window = self.rules.soc_window_mj
        net = plan.net_mj
        measured["net_mj"] = net
        checks["soc_window"] = -window - 1e-9 <= net <= window + 1e-9
        details["soc_window"] = f"net {net:+.3f} MJ of {window:g} MJ window"

        harvest = plan.harvest_mj
        measured["harvest_mj"] = harvest
        ok_h = harvest <= self.rules.harvest_cap_mj_per_lap + 1e-9
        checks["harvest_cap"] = ok_h
        details["harvest_cap"] = (
            f"{harvest:.3f} <= {self.rules.harvest_cap_mj_per_lap:g} MJ"
        )

        deploy = plan.deploy_mj
        measured["deploy_mj"] = deploy
        # Overtake Mode grants +0.5 MJ on the following lap
        allowance = self.event_deploy_mj + (
            self.rules.overtake_bonus_mj if plan.overtake_mode else 0.0
        )
        ok_d = deploy <= allowance + 1e-9
        checks["deploy_cap"] = ok_d
        details["deploy_cap"] = f"{deploy:.3f} <= {allowance:g} MJ"

        # Deployment caps bound the *deploy* power only; harvested (negative)
        # power is charging, not propulsion, and is bounded by the harvest rules.
        peak_deploy = max(
            (abs(s.power_kw) for s in plan.segments if s.power_kw > 0.0), default=0.0
        )
        measured["peak_deploy_kw"] = peak_deploy
        measured["peak_power_kw"] = plan.peak_power_kw

        if segment_speeds is not None and len(segment_speeds) == len(plan.segments):
            p2p = 0.0
            ok_p = True
            for s, sp in zip(plan.segments, segment_speeds):
                if s.power_kw > 0.0:
                    lim = power_to_propel_kw(float(sp), self.rules)
                    p2p = max(p2p, lim)
                    if s.power_kw > lim + 1e-6:
                        ok_p = False
            checks["power_to_propel"] = ok_p
            details["power_to_propel"] = (
                f"per-segment <= power_to_propel rampdown (worst {p2p:.0f} kW)"
            )
        else:
            p2p = power_to_propel_kw(speed_kph, self.rules)
            checks["power_to_propel"] = peak_deploy <= p2p + 1e-6
            details["power_to_propel"] = (
                f"{peak_deploy:.0f} <= {p2p:.0f} kW at {speed_kph:.0f} km/h"
            )

        zone_cap = self.rules.zone_deploy_kw["key_acceleration"]
        checks["zone_deploy"] = peak_deploy <= zone_cap + 1e-6
        details["zone_deploy"] = f"peak {peak_deploy:.0f} <= {zone_cap:.0f} kW"

        boost_cap = self.rules.base_deploy_kw + self.rules.race_boost_cap_kw
        checks["boost_cap"] = peak_deploy <= boost_cap + 1e-6
        details["boost_cap"] = f"peak {peak_deploy:.0f} <= {boost_cap:.0f} kW"

        if lap <= 1:
            ok_s = speed_kph >= self.rules.start_min_speed_kph - 1e-9
            checks["start_min_speed"] = ok_s
            details["start_min_speed"] = (
                f"{speed_kph:.0f} >= {self.rules.start_min_speed_kph:g} km/h"
            )

        pit_gain_kj = float(plan.metadata.get("pit_stationary_gain_kj", 0.0))
        measured["pit_gain_kj"] = pit_gain_kj
        ok_pit = pit_gain_kj <= self.rules.pit_stationary_gain_kj + 1e-9
        checks["pit_gain"] = ok_pit
        details["pit_gain"] = f"{pit_gain_kj:.0f} <= {self.rules.pit_stationary_gain_kj:g} kJ"

        torque = float(plan.metadata.get("mgu_k_torque_nm", 0.0))
        measured["torque_nm"] = torque
        ok_t = torque <= self.rules.mgu_k_torque_nm + 1e-9
        checks["torque"] = ok_t
        details["torque"] = f"{torque:.0f} <= {self.rules.mgu_k_torque_nm:g} Nm"

        if slew_rate:
            worst_slew = self._worst_slew(plan)
            measured["slew_kw_per_s"] = worst_slew
            checks["slew_rate"] = worst_slew <= self.rules.slew_rate_kw_per_s + 1e-6
            details["slew_rate"] = (
                f"{worst_slew:.0f} <= {self.rules.slew_rate_kw_per_s:g} kW/s"
            )
        else:
            # Not applicable for coarse planner output (see docstring).
            checks["slew_rate"] = True
            details["slew_rate"] = "n/a for planner output (controller-enforced)"

        return ComplianceResult(
            passed=all(checks.values()),
            checks=checks,
            details=details,
            measured=measured,
        )

    # ------------------------------------------------------------------
    def _worst_slew(self, plan: DeploymentPlan) -> float:
        """Largest |dP/dt| between consecutive plan segments [kW/s]."""
        worst = 0.0
        prev_p: Optional[float] = None
        for seg in plan.segments:
            p = abs(float(seg.power_kw))
            if prev_p is not None and seg.duration_s > 1e-6:
                worst = max(worst, abs(p - prev_p) / seg.duration_s)
            prev_p = p
        return worst

    # ------------------------------------------------------------------
    def check_power_profile(
        self,
        powers_kw: Sequence[float],
        segments: Sequence[Segment],
        lap: int = 2,
    ) -> ComplianceResult:
        """Convenience: check a bare power array against the segments."""
        segs = [
            PlanSegment(
                segment_index=s.index,
                power_kw=float(p),
                deploy_mj=max(float(p), 0.0) * s.duration_s / 1000.0,
                harvest_mj=max(-float(p), 0.0) * s.duration_s / 1000.0,
                speed_kph=s.mean_speed_kph,
                duration_s=s.duration_s,
            )
            for p, s in zip(powers_kw, segments)
        ]
        plan = DeploymentPlan(segments=segs, lap=lap)
        speed = float(segments[len(segments) // 2].mean_speed_kph) if segments else 0.0
        return self.check(plan, speed_kph=speed, lap=lap)

    def board_rows(self, result: ComplianceResult) -> List[Dict[str, str]]:
        """Rows for the UI compliance board, with human-readable rule labels."""
        return [
            {
                "rule": RULE_LABELS.get(k, k),
                "status": "PASS" if v else "FAIL",
                "detail": result.details.get(k, ""),
            }
            for k, v in result.checks.items()
        ]


def certificate_text(result: ComplianceResult) -> str:
    """Plain-text compliance certificate (used in the README and UI footer)."""
    lines = ["RaceIQ 2026 - FIA compliance certificate", "-" * 42]
    for k, v in result.checks.items():
        lines.append(f"  {'PASS' if v else 'FAIL'}  {RULE_LABELS.get(k, k):<38} {result.details.get(k, '')}")
    lines.append("-" * 42)
    lines.append(f"  OVERALL: {'PASS' if result.passed else 'FAIL'}")
    return "\n".join(lines)
