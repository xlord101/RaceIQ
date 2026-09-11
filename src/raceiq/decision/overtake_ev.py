"""Overtake EV engine - the priced bet at the Detection Line.

At the Detection Line, if the chasing car is within the event Detection Gap, we
price the overtake as a legal bet:

    EV = P(pass) * points_gain
         - repass_cost_pts            # yo-yo: rival re-passes you next lap
         - repayment_pts              # time-energy debt to harvest back
         - lambda_illegal * illegal   # huge penalty if non-compliant

and return ``GO`` / ``HOLD`` plus a full breakdown. ``P(pass)`` comes from
:class:`~raceiq.decision.pass_model.PassModel`; the rival's hidden-state belief
(the 8-state HMM) supplies the trap flag and the ``Lderate``/``Lharvest``
marginals that make "looks slow" vs "is empty" matter.

The counter-harvest trap is a **hard override**: when the HMM says the rival is
deliberately conserving in the aero zone, the engine returns ``HOLD``
regardless of the raw EV - attacking a trap is the classic fatal bet.

Master instruction #5: every FIA / scoring constant is read from
``config/rules_2026.json`` (via :class:`~raceiq.config.RulesConfig`), never
hard-coded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from raceiq.config import EventConfig, RulesConfig, load_rules
from raceiq.decision.pass_model import PassModel
from raceiq.types import Belief, OvertakeDecision

__all__ = ["OvertakeContext", "OvertakeEV"]


@dataclass
class OvertakeContext:
    """Inputs to the Overtake EV engine for one detection event.

    All SoC / ERS values are **estimates** (the observer and HMM produce them);
    nothing here is a published quantity.
    """

    gap_ahead_s: float = 1.0
    closing_speed_kph: float = 0.0
    straight_remaining_m: float = 0.0
    tyre_age_delta_laps: float = 0.0
    own_est_soc: float = 2.0
    rival_est_soc: float = 2.0
    belief: Optional[Belief] = None
    overtake_mode_active: bool = False
    circuit_harvest_potential_mj: float = 3.0
    laps_remaining: int = 10
    position_before: Optional[int] = None
    detection_gap_s: Optional[float] = None
    legal: bool = True


class OvertakeEV:
    """Price a single overtaking opportunity as a legal bet."""

    def __init__(
        self,
        config: Optional[RulesConfig] = None,
        pass_model: Optional[PassModel] = None,
        event: Optional[EventConfig] = None,
    ) -> None:
        self.config = config or load_rules()
        self.event = event
        self.pass_model = pass_model or PassModel()

    # ------------------------------------------------------------------
    def _points_gain(self, ctx: OvertakeContext) -> float:
        """Expected points for a single-position gain (pass one car = +1)."""
        pts = self.config.points
        by_pos = {
            int(k): float(v) for k, v in pts["by_finish_position"].items()
        }
        default = float(pts.get("default_position_gain_points", 2.0))
        pb = ctx.position_before
        if pb is None:
            return default
        pa = pb - 1  # passing one car is +1 track position
        gain = by_pos.get(pa, by_pos.get(10, 0.0)) - by_pos.get(pb, 0.0)
        if gain <= 0.0:
            return default
        return float(gain)

    def _repayment_seconds(self, ctx: OvertakeContext) -> float:
        """Race-time cost [s] of harvesting back the overtake energy debt.

        Overtake Mode spends a ``+bonus`` MJ plus the extra deployment of an
        attacking lap. That energy must be harvested back over subsequent laps,
        forgoing deploy on the straights. The cost is **circuit-dependent**:
        a high-harvest circuit (Baku ~7.1 MJ/lap) repays faster than a
        low-harvest one (Monza ~3.3 MJ/lap), matching the spec note that
        "Monza repays slower than Baku".
        """
        deploy_delta = 0.0
        if self.event is not None:
            deploy_delta = max(
                0.0,
                self.event.deploy_mj_with_overtake
                - self.event.deploy_mj_without_overtake,
            )
        extra_mj = float(self.config.overtake_bonus_mj) + deploy_delta
        per_lap_s = float(self.config.points.get("repayment_cost_per_lap_s", 0.4))
        harvest = max(float(ctx.circuit_harvest_potential_mj), 0.1)
        return extra_mj / harvest * per_lap_s

    # ------------------------------------------------------------------
    def evaluate(
        self, ctx: OvertakeContext, frontier: Any = None
    ) -> OvertakeDecision:
        """Price the overtake and return ``GO`` / ``HOLD`` plus breakdown.

        Parameters
        ----------
        ctx:
            The detection-event inputs (gap, belief, SoC estimates, ...).
        frontier:
            Optional Tier-1 Pareto frontier (accepted for API symmetry with the
            spec; the bet itself is priced from ``P(pass)`` and the energy debt).

        Returns
        -------
        OvertakeDecision
        """
        cfg = self.config
        pts = cfg.points

        # --- eligibility (proximity-gated, event overrides rules default) ---
        if ctx.detection_gap_s is not None:
            detection_gap = float(ctx.detection_gap_s)
        elif self.event is not None:
            detection_gap = float(self.event.detection_gap_s)
        else:
            detection_gap = float(cfg.detection_gap_s)
        eligible = float(ctx.gap_ahead_s) <= detection_gap

        # --- rival hidden-state / trap ---
        if ctx.belief is not None:
            p_ld = float(ctx.belief.p_Lderate)
            p_lh = float(ctx.belief.p_Lharvest)
            p_ot_avail = float(ctx.belief.p_overtake_available)
            trap_flag = bool(ctx.belief.trap_flag)
        else:
            p_ld = p_lh = p_ot_avail = 0.0
            trap_flag = False

        # --- P(pass) from the (trained or heuristic) model ---
        features = {
            "gap_ahead_s": float(ctx.gap_ahead_s),
            "closing_speed_kph": float(ctx.closing_speed_kph),
            "straight_remaining_m": float(ctx.straight_remaining_m),
            "tyre_age_delta_laps": float(ctx.tyre_age_delta_laps),
            "own_est_soc": float(ctx.own_est_soc),
            "rival_est_soc": float(ctx.rival_est_soc),
            "rival_P_Lderate": p_ld,
            "rival_P_Lharvest": p_lh,
            "trap_flag": 1.0 if trap_flag else 0.0,
            "overtake_mode_active": 1.0 if ctx.overtake_mode_active else 0.0,
            "circuit_harvest_potential_mj": float(ctx.circuit_harvest_potential_mj),
            "laps_remaining": float(ctx.laps_remaining),
        }
        p_pass = float(self.pass_model.predict_proba(features))
        p_pass = min(max(p_pass, 0.0), 1.0)

        # --- P(pass) capped down when the rival is a trap (deliberately slow) ---
        if trap_flag:
            p_pass = min(p_pass, 0.25)

        # --- valuation terms ---
        points_gain = self._points_gain(ctx)
        repayment_s = self._repayment_seconds(ctx)
        repayment_pts = repayment_s * float(
            pts.get("repayment_points_per_second", 5.0)
        )

        # Yo-yo / repass: after you pass, the rival is behind you within the
        # Detection Gap and gets Overtake against you. Probability they can =
        # they still have Overtake available AND are not genuinely empty.
        repass_risk = min(1.0, max(0.0, p_ot_avail * (1.0 - p_ld)))
        repass_cost_pts = repass_risk * points_gain

        legal = bool(ctx.legal)
        illegal_penalty = 0.0 if legal else float(pts.get("lambda_illegal", 1000.0))

        ev = (
            p_pass * points_gain
            - repass_cost_pts
            - repayment_pts
            - illegal_penalty
        )

        # --- decision: trap / ineligible / illegal all force HOLD ---
        if trap_flag or (not eligible) or (not legal):
            go = "HOLD"
            recommendation = "HOLD"
        else:
            go = "GO" if ev > 0.0 else "HOLD"
            recommendation = "ATTACK" if go == "GO" else "HOLD"

        status = "legal" if legal else "ILLEGAL"
        go_verb = "GO" if go == "GO" else "HOLD"
        why = (
            f"{p_pass * 100:.0f}% pass, costs {repayment_s:.1f}s to recharge, "
            f"{repass_risk * 100:.0f}% repass risk, {status} -> {go_verb}"
        )
        if trap_flag:
            why = (
                "COUNTER-HARVEST TRAP - rival conserving in aero zone; " + why
            )

        breakdown: Dict[str, float] = {
            "p_pass": p_pass,
            "points_gain": points_gain,
            "repass_cost_pts": repass_cost_pts,
            "repayment_cost_s": repayment_s,
            "repayment_pts": repayment_pts,
            "illegal_penalty": illegal_penalty,
            "ev": ev,
        }

        return OvertakeDecision(
            go=go,
            recommendation=recommendation,
            p_pass=p_pass,
            points_gain=points_gain,
            repayment_cost_s=repayment_s,
            repass_risk=repass_risk,
            legal=legal,
            trap_flag=trap_flag,
            eligible=eligible,
            ev=ev,
            why=why,
            breakdown=breakdown,
            gap_s=float(ctx.gap_ahead_s),
        )
