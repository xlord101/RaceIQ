"""Counterfactual What-If branch builder.

Bridges the export-time factual replay pipeline to the existing Tier-2
scenario-tree optimiser. Given a frozen replay state it rolls each strategic
posture forward over the horizon and serialises **model-derived** projections.

The frontend never re-computes these: branches are model-generated during
RaceIQ data preparation from the frozen replay state. Nothing here invents
values - inputs the model does not have are listed in ``inputsUnavailable``
and known analytical approximations are listed in ``inputApproximations``.

UI action -> Tier-2 posture plan (one mapping, documented):
    ATTACK -> ATTACK, HOLD -> NEUTRAL, DEFEND -> DEFEND, HARVEST -> HARVEST
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from raceiq.optimize.tier2_mpc import MPCState, Tier2MPC
from raceiq.optimize.tier2_mpc import _SOC_RESERVE_FRAC as _RESERVE_FRAC

__all__ = ["build_whatif_branches"]

_ACTION_TO_TIER2 = {
    "ATTACK": "ATTACK",
    "HOLD": "NEUTRAL",
    "DEFEND": "DEFEND",
    "HARVEST": "HARVEST",
}

_DEFAULT_HORIZON = 8

# Known analytical approximations in the current adapter path, documented
# rather than hidden: these are NOT measured telemetry and the UI styles them
# accordingly (APPROXIMATION - INFERRED, not ACTUAL).
_INPUT_APPROXIMATIONS = {
    "closing_speed_kph": "analytical approximation from sampled speed, not measured",
    "straight_remaining_m": "static circuit estimate, not measured",
    "overtake_mode_active": "not directly observed; not claimed as telemetry",
}


def _risk(res: Dict[str, Any], state: MPCState, action: str) -> str:
    """Risk band derived from the simulated rollout, not a canned label."""
    window = float(state.soc_window_mj)
    floor = _RESERVE_FRAC * window
    if res["repasses_behind"] > 0 or res["min_soc"] < floor:
        return "HIGH"
    if (
        action == "ATTACK"
        and state.belief_ahead is not None
        and bool(state.belief_ahead.trap_flag)
    ):
        return "HIGH"
    if res["time_lost_behind"] > 0 or res["min_soc"] < 2.0 * floor:
        return "MEDIUM"
    return "LOW"


def _outcome(
    action: str, res: Dict[str, Any], state: MPCState, horizon: int
) -> str:
    """Outcome text composed only from what the rollout actually projected."""
    bits: List[str] = []
    n_pass = int(res["passes_ahead"])
    if n_pass > 0:
        plural = "s" if n_pass > 1 else ""
        bits.append(
            f"Projects {n_pass} position{plural} gained within the "
            f"{horizon}-lap horizon."
        )
    else:
        bits.append(
            f"Position maintained over the {horizon}-lap horizon; gap ahead "
            f"ends near {res['final_gap_ahead']:.1f}s."
        )
    if res["repasses_behind"] > 0:
        bits.append("Projected position at risk from the car behind.")
    soc_start = float(state.own_est_soc_mj)
    if res["final_soc"] > soc_start + 1e-6:
        pct = 100.0 * res["final_soc"] / float(state.soc_window_mj)
        bits.append(f"Estimated battery reserve builds to about {pct:.0f}%.")
    elif res["final_soc"] < soc_start - 1e-6:
        bits.append("Estimated battery reserve declines over the horizon.")
    if (
        action == "ATTACK"
        and state.belief_ahead is not None
        and bool(state.belief_ahead.trap_flag)
    ):
        bits.append(
            "Rival ahead appears to be conserving (counter-harvest); "
            "attack carries elevated risk."
        )
    return " ".join(bits)


def build_whatif_branches(
    mpc: Tier2MPC,
    state: MPCState,
    position: Optional[int] = None,
    horizon: Optional[int] = None,
) -> Dict[str, Dict[str, Any]]:
    """Roll every UI posture forward and return model-derived branch dicts.

    ``state.gap_behind_s`` may be ``None`` (no car behind); the rollout then
    skips behind dynamics and the branch reports the absence honestly instead
    of a fabricated gap.
    """
    h = _DEFAULT_HORIZON if horizon is None else max(1, int(horizon))
    # The horizon can never exceed the laps actually left in the race.
    if state.laps_remaining and int(state.laps_remaining) > 0:
        h = min(h, int(state.laps_remaining))

    unavailable: List[str] = []
    if state.belief_ahead is None:
        unavailable.append("belief_ahead")
    if state.belief_behind is None:
        unavailable.append("belief_behind")
    if state.gap_behind_s is None:
        unavailable.append("gap_behind")

    branches: Dict[str, Dict[str, Any]] = {}
    for action, tier2_posture in _ACTION_TO_TIER2.items():
        res = mpc.simulate_posture(tier2_posture, state, h)
        energy_spend = float(sum(res["per_lap_net"]))
        branch: Dict[str, Any] = {
            "projectedGap": round(float(res["final_gap_ahead"]), 3),
            "projectedSoc": round(
                min(
                    1.0,
                    max(0.0, float(res["final_soc"]) / float(state.soc_window_mj)),
                ),
                4,
            ),
            "energySpendMj": round(energy_spend, 3),
            "minSocMj": round(float(res["min_soc"]), 3),
            "passesAhead": int(res["passes_ahead"]),
            "repassesBehind": int(res["repasses_behind"]),
            "score": round(float(res["score"]), 2),
            "horizonLaps": int(h),
            "risk": _risk(res, state, action),
            "outcome": _outcome(action, res, state, h),
        }
        if position is not None:
            branch["projectedPosition"] = int(
                max(
                    1,
                    int(position)
                    - int(res["passes_ahead"])
                    + int(res["repasses_behind"]),
                )
            )
        if unavailable:
            branch["inputsUnavailable"] = sorted(unavailable)
        branch["inputApproximations"] = dict(_INPUT_APPROXIMATIONS)
        branches[action] = branch
    return branches
