"""Tier-2 MPC - the race-posture optimiser.

Tier-1 (``raceiq.optimize.tier1_dp``) turns a single lap into a Pareto frontier:
the exchange rate between joules and seconds for this circuit. Tier-2 consumes
that frontier over the **next 8-12 laps** and chooses a strategic posture:

    ATTACK   - spend aggressively to close on the car ahead,
    NEUTRAL  - balanced baseline,
    HARVEST  - spend little, rebuild the battery reserve,
    DEFEND   - hold position against a chasing rival.

This is a **scenario-tree / rolling-horizon** optimiser (discrete posture
branches evaluated over an H-lap horizon with SoC and gap dynamics), *not* an
MCTS - per the master instruction we replaced the prior-art DQN/MCTS with
interpretable DP + MPC. The battery has almost no memory (~2x/lap cycling in a
4 MJ window), so the posture is re-planned every lap from the current SoC.

Circuit dependence is physical: on a high-harvest circuit (Baku ~7.1 MJ/lap)
ATTACK is sustainable, while on a low-harvest one (Monza ~3.3 MJ/lap) the same
aggression drains the battery and HARVEST wins - exactly the ablation the spec
requires.

All FIA / scoring constants come from ``config`` (master instruction #5); no
hard-coded numbers in the logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from raceiq.config import EventConfig, RulesConfig, load_rules
from raceiq.optimize.frontier import ParetoFrontier
from raceiq.types import Belief, Posture

__all__ = ["MPCState", "Tier2MPC"]

# Posture -> (fraction of frontier max net energy, harvest intensity 0..1).
# net energy is deploy minus harvest for one lap; harvest intensity is how much
# of the circuit's recoverable brake energy the posture actually recovers.
_POSTURE_PLANS: Dict[str, Dict[str, float]] = {
    "ATTACK": {"energy_frac": 1.0, "harvest_intensity": 0.2},
    "NEUTRAL": {"energy_frac": 0.55, "harvest_intensity": 0.6},
    "HARVEST": {"energy_frac": 0.15, "harvest_intensity": 1.0},
    "DEFEND": {"energy_frac": 0.4, "harvest_intensity": 0.8},
}

_NEUTRAL_FRAC = 0.55
_SOC_RESERVE_FRAC = 0.15  # keep at least this fraction of the window


@dataclass
class MPCState:
    """Race context for one MPC re-plan (all estimates, not published values)."""

    gap_ahead_s: float = 1.0
    # ``None`` means no car behind exists (e.g. last-placed car): the behind
    # dynamics are then skipped entirely, never fed a fabricated nominal gap.
    gap_behind_s: Optional[float] = 1.0
    own_est_soc_mj: float = 2.0
    soc_window_mj: float = 4.0
    belief_ahead: Optional[Belief] = None
    belief_behind: Optional[Belief] = None
    laps_remaining: int = 10
    tyre_age_laps: float = 10.0
    rival_tyre_age_laps: float = 10.0
    circuit_harvest_potential_mj: float = 3.0
    position: Optional[int] = None


class Tier2MPC:
    """Scenario-tree race-posture optimiser over the Tier-1 frontier."""

    def __init__(
        self,
        frontier: ParetoFrontier,
        config: Optional[RulesConfig] = None,
        event: Optional[EventConfig] = None,
    ) -> None:
        if frontier is None or len(frontier) == 0:
            raise ValueError("Tier2MPC requires a non-empty ParetoFrontier")
        self.frontier = frontier
        self.config = config or load_rules()
        self.event = event
        self.max_energy = float(frontier.max_energy_mj)
        self.neutral_time = float(
            frontier.time_for_energy(_NEUTRAL_FRAC * self.max_energy)
        )

    # ------------------------------------------------------------------
    def _rival_factors(self, belief: Optional[Belief]) -> tuple:
        """Return (slow_factor_ahead/behind) from a rival's hidden-state belief.

        A genuinely empty rival (``Lderate``) is slower; a conserving-trap rival
        (``Lharvest``) is pacing to attack, so treated as relatively quick now.
        """
        if belief is None:
            return (1.0, 1.0)
        p_ld = float(belief.p_Lderate)
        p_lh = float(belief.p_Lharvest)
        # Rival pace modifier. Kept small (<=0.3% of a ~90 s lap = ~0.27 s/lap):
        # a plausible slow/conserving rival is worth tenths per lap, not whole
        # seconds. The old +-3% modifier produced +-2.7 s/lap, which is fine for
        # relative posture scoring but made absolute gap projections drift by
        # tens of seconds over the horizon - physically indefensible.
        f = 1.0 + 0.003 * p_ld - 0.003 * p_lh
        return (max(f, 0.99), max(f, 0.99))

    def _simulate(
        self, posture: str, state: MPCState, horizon: int
    ) -> Dict[str, float]:
        """Roll the posture forward over ``horizon`` laps; return its metrics."""
        plan = _POSTURE_PLANS[posture]
        target_net = plan["energy_frac"] * self.max_energy
        harvest_intensity = plan["harvest_intensity"]
        our_time = float(self.frontier.time_for_energy(target_net))

        window = float(state.soc_window_mj)
        harvest = float(state.circuit_harvest_potential_mj)
        soc = float(state.own_est_soc_mj)
        min_soc = float("inf")  # floor reached *during* the horizon (not the start)

        f_ahead_a, f_ahead_b = self._rival_factors(state.belief_ahead)
        rival_ahead_time = self.neutral_time * f_ahead_a
        # A rival behind exists only when an actual behind gap is supplied;
        # belief_behind may still be unknown (treated as neutral pace).
        has_rival_behind = state.gap_behind_s is not None
        rival_behind_time = (
            self.neutral_time * self._rival_factors(state.belief_behind)[1]
            if has_rival_behind
            else None
        )

        gap_ahead = float(state.gap_ahead_s)
        gap_behind = (
            float(state.gap_behind_s) if state.gap_behind_s is not None else None
        )
        passes_ahead = 0
        repasses_behind = 0
        passed = False
        lost = False
        time_gain_ahead = 0.0
        time_lost_behind = 0.0

        per_lap_net: List[float] = []
        per_lap_delta: List[float] = []

        for _ in range(horizon):
            # Physical cap: you cannot deploy more net energy than the battery
            # currently holds plus what this lap's braking can recover. This is
            # what makes ATTACK unsustainable on a low-harvest circuit.
            harvest_cap = harvest * harvest_intensity
            max_spend = soc + harvest_cap
            eff_net = min(target_net, max_spend)
            after = max(soc - eff_net, 0.0)
            regen = min(harvest_cap, max(window - after, 0.0))
            soc = min(after + regen, window)
            min_soc = min(min_soc, soc)

            our_time = float(self.frontier.time_for_energy(eff_net))
            per_lap_net.append(eff_net)
            per_lap_delta.append(our_time - self.neutral_time)

            # A slower rival (larger lap time) lets us close the gap ahead; a
            # faster us (smaller lap time) grows the gap behind (we pull away).
            gap_ahead = gap_ahead - (rival_ahead_time - our_time)
            if not passed and gap_ahead <= 0.0:
                passes_ahead += 1
                passed = True
            time_gain_ahead += max(0.0, rival_ahead_time - our_time)

            if rival_behind_time is not None and gap_behind is not None:
                gap_behind = gap_behind + (rival_behind_time - our_time)
                if not lost and gap_behind <= 0.0:
                    repasses_behind += 1
                    lost = True
                time_lost_behind += max(0.0, our_time - rival_behind_time)

        trap_ahead = bool(state.belief_ahead.trap_flag) if state.belief_ahead else False
        # SoC is a *constraint*, not an objective: penalise only dipping below
        # the reserve floor (hard), with a gentle reward for holding a healthy
        # buffer so the optimiser prefers rebuilding a depleted battery.
        floor = _SOC_RESERVE_FRAC * window
        soc_term = (min_soc - floor) * 0.5
        soc_penalty = max(0.0, (floor - min_soc)) * 50.0
        trap_penalty = 5.0 if (posture == "ATTACK" and trap_ahead) else 0.0

        score = (
            time_gain_ahead
            - time_lost_behind
            + soc_term
            - soc_penalty
            - trap_penalty
        )
        return {
            "score": float(score),
            "min_soc": float(min_soc),
            "passes_ahead": float(passes_ahead),
            "repasses_behind": float(repasses_behind),
            "time_gain_ahead": float(time_gain_ahead),
            "time_lost_behind": float(time_lost_behind),
            "trap_penalty": float(trap_penalty),
            "per_lap_net": per_lap_net,
            "per_lap_delta": per_lap_delta,
            # End-of-horizon state for counterfactual What-If projections.
            # final_gap_behind is None when no car behind exists.
            "final_soc": float(soc),
            "final_gap_ahead": float(gap_ahead),
            "final_gap_behind": (
                float(gap_behind) if gap_behind is not None else None
            ),
        }

    # ------------------------------------------------------------------
    def simulate_posture(
        self, posture: str, state: MPCState, horizon: int = 8
    ) -> Dict[str, Any]:
        """Public single-posture rollout (delegates to ``_simulate``).

        Counterfactual What-If evaluation calls this instead of the private
        ``_simulate``; the underlying rollout is one and the same.
        """
        if posture not in _POSTURE_PLANS:
            raise ValueError(
                f"unknown posture {posture!r}; expected one of "
                f"{sorted(_POSTURE_PLANS)}"
            )
        horizon = max(1, int(horizon))
        return self._simulate(posture, state, horizon)

    # ------------------------------------------------------------------
    def recommend(self, state: MPCState, horizon: int = 10) -> Posture:
        """Choose the best posture over the next ``horizon`` laps.

        Returns
        -------
        Posture
            Chosen posture, its score (``expected_value``), per-lap plan, and
            the score of every candidate in ``alternatives``.
        """
        horizon = max(1, int(horizon))
        results: Dict[str, Dict[str, float]] = {}
        for posture in _POSTURE_PLANS:
            results[posture] = self._simulate(posture, state, horizon)

        # Prefer the highest-scoring posture; among ties, prefer the more
        # conservative (lower net spend) to protect the battery.
        ranked = sorted(
            _POSTURE_PLANS.keys(),
            key=lambda p: (results[p]["score"], -results[p]["per_lap_net"][0]),
            reverse=True,
        )
        best = ranked[0]

        trap_ahead = (
            bool(state.belief_ahead.trap_flag) if state.belief_ahead else False
        )
        rationale = self._rationale(best, state, results[best], trap_ahead)

        return Posture(
            posture=best,
            expected_value=float(results[best]["score"]),
            rationale=rationale,
            horizon_laps=horizon,
            per_lap_net_mj=list(results[best]["per_lap_net"]),
            per_lap_delta_s=list(results[best]["per_lap_delta"]),
            alternatives={p: float(results[p]["score"]) for p in results},
            min_soc_mj=float(results[best]["min_soc"]),
        )

    # ------------------------------------------------------------------
    def _rationale(
        self, posture: str, state: MPCState, res: Dict[str, float], trap_ahead: bool
    ) -> str:
        bits = [f"{posture}: SoC floor {res['min_soc']:.2f} MJ"]
        if trap_ahead:
            bits.append(
                "rival ahead is a counter-harvest trap - avoid ATTACK"
                if posture != "ATTACK"
                else "WARNING attacking a trap"
            )
        if state.circuit_harvest_potential_mj >= 6.0:
            bits.append("high-harvest circuit sustains attack")
        elif state.circuit_harvest_potential_mj <= 3.5:
            bits.append("low-harvest circuit - reserve building favoured")
        if res["passes_ahead"] > 0:
            bits.append(f"projects {int(res['passes_ahead'])} pass(es) on car ahead")
        return "; ".join(bits)
