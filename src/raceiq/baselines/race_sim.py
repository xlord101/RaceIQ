"""Offline race simulator used to compare energy strategies head-to-head.

Given the Tier-1 Pareto ``frontier`` (the price of energy for a circuit) and a
``Strategy`` that picks a per-lap target net spend, the simulator rolls the
battery and a simple rival model forward lap by lap. It is deliberately
*physics-faithful but minimal*: the battery (4 MJ window) is the binding
constraint, harvest is circuit-limited, and you cannot deploy more than the
battery holds plus what braking recovers that lap.

Strategies compared:
    * Greedy       - attack (max deploy) whenever within the Detection Gap,
    * Conservative - harvest/save in the late laps, never attack,
    * RaceIQ       - the Tier-2 MPC posture optimiser (``baselines.compare``).

This is the engine behind the "RaceIQ vs Greedy vs Conservative" table the
spec requires (Sections 8 and 13).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol, runtime_checkable

import numpy as np

from raceiq.config import RulesConfig, load_rules
from raceiq.optimize.frontier import ParetoFrontier
from raceiq.optimize.tier2_mpc import MPCState


@dataclass
class SimResult:
    """Outcome of simulating one strategy over a race replay."""

    name: str
    laps: int
    target_net_mj: List[float] = field(default_factory=list)
    eff_net_mj: List[float] = field(default_factory=list)
    soc_mj: List[float] = field(default_factory=list)
    lap_time_s: List[float] = field(default_factory=list)
    gap_ahead_s: List[float] = field(default_factory=list)
    net_position_delta: int = 0
    min_soc_mj: float = 0.0
    attack_laps: int = 0
    final_gap_ahead_s: float = 0.0

    @property
    def total_time_s(self) -> float:
        """Sum of lap times [s]."""
        return float(sum(self.lap_time_s))


@runtime_checkable
class Strategy(Protocol):
    """Anything that returns a target net energy [MJ] for the next lap."""

    name: str

    def plan(self, state: MPCState, frontier: ParetoFrontier, horizon: int) -> float:
        """Return the target net energy spend [MJ] for the upcoming lap."""
        ...


class RaceSimulator:
    """Roll a race forward under a fixed energy strategy and rival model."""

    def __init__(
        self,
        frontier: ParetoFrontier,
        config: Optional[RulesConfig] = None,
        *,
        circuit_harvest_potential_mj: float = 3.0,
        soc_window_mj: float = 4.0,
        detection_gap_s: float = 1.0,
        rival_pace_s: float = 90.0,
        start_gap_ahead_s: float = 1.0,
        start_gap_behind_s: float = 1.0,
        pack_reset_gap_s: Optional[float] = None,
    ) -> None:
        self.frontier = frontier
        self.config = config or load_rules()
        self.window = float(soc_window_mj)
        self.harvest = float(circuit_harvest_potential_mj)
        self.detection_gap_s = float(detection_gap_s)
        self.rival_pace_s = float(rival_pace_s)
        self.start_gap_ahead_s = float(start_gap_ahead_s)
        self.start_gap_behind_s = float(start_gap_behind_s)
        # Pack racing: when you fall more than this behind, a new rival appears
        # at the Detection Gap (models being in a train of cars). None = solo.
        self.pack_reset_gap_s = None if pack_reset_gap_s is None else float(pack_reset_gap_s)
        self.max_energy = float(frontier.max_energy_mj)

    # ------------------------------------------------------------------
    def simulate(
        self,
        strategy: Strategy,
        laps: int = 20,
        initial_soc_mj: float = 2.5,
        horizon: int = 10,
    ) -> SimResult:
        """Run ``strategy`` for ``laps`` laps; return the tallied result."""
        soc = float(initial_soc_mj)
        gap_ahead = self.start_gap_ahead_s
        gap_behind = self.start_gap_behind_s
        pos_delta = 0

        res = SimResult(name=getattr(strategy, "name", "strategy"), laps=laps)

        for lap in range(1, laps + 1):
            laps_remaining = laps - lap + 1
            state = MPCState(
                gap_ahead_s=gap_ahead,
                gap_behind_s=gap_behind,
                own_est_soc_mj=soc,
                soc_window_mj=self.window,
                circuit_harvest_potential_mj=self.harvest,
                laps_remaining=laps_remaining,
            )
            target = float(strategy.plan(state, self.frontier, horizon))
            target = min(max(target, 0.0), self.max_energy)

            # Physics-faithful recovery: attacking (high net) recovers little
            # spare brake energy; harvesting (low net) recovers nearly all.
            harvest_intensity = max(0.0, 1.0 - target / self.max_energy)
            harvest_cap = self.harvest * harvest_intensity

            max_spend = soc + harvest_cap
            eff_net = min(target, max_spend)
            after = max(soc - eff_net, 0.0)
            regen = min(harvest_cap, max(self.window - after, 0.0))
            soc = min(after + regen, self.window)

            lap_time = float(self.frontier.time_for_energy(eff_net))

            # Position dynamics vs a single rival running at rival_pace_s.
            gap_ahead = gap_ahead - (self.rival_pace_s - lap_time)
            gap_behind = gap_behind + (self.rival_pace_s - lap_time)
            if gap_ahead <= 0.0 and lap_time < self.rival_pace_s:
                pos_delta += 1
            if gap_behind <= 0.0 and lap_time > self.rival_pace_s:
                pos_delta -= 1

            # Pack racing: falling far back drops you onto the next car's gear,
            # which sits at the Detection Gap - so the fight restarts.
            if self.pack_reset_gap_s is not None and gap_ahead > self.pack_reset_gap_s:
                gap_ahead = self.detection_gap_s

            res.target_net_mj.append(target)
            res.eff_net_mj.append(eff_net)
            res.soc_mj.append(soc)
            res.lap_time_s.append(lap_time)
            res.gap_ahead_s.append(gap_ahead)
            if target >= 0.9 * self.max_energy:
                res.attack_laps += 1

        res.net_position_delta = pos_delta
        res.min_soc_mj = float(min(res.soc_mj)) if res.soc_mj else 0.0
        res.final_gap_ahead_s = float(res.gap_ahead_s[-1]) if res.gap_ahead_s else 0.0
        return res
