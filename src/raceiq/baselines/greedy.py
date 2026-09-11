"""Greedy baseline: attack whenever within the Detection Gap.

The reference "do the obvious thing" strategy - deploy maximum energy on any lap
where the car ahead is within the event Detection Gap, otherwise run neutral.
It ignores battery sustainability, so on a low-harvest circuit it depletes the
4 MJ window and slows down - which is exactly what RaceIQ is meant to beat.
"""

from __future__ import annotations

from typing import Optional

from raceiq.config import EventConfig, RulesConfig, load_rules
from raceiq.optimize.frontier import ParetoFrontier
from raceiq.optimize.tier2_mpc import MPCState


class GreedyStrategy:
    """Max-deploy whenever the rival ahead is within the Detection Gap."""

    name = "Greedy"

    def __init__(
        self,
        config: Optional[RulesConfig] = None,
        event: Optional[EventConfig] = None,
    ) -> None:
        self.config = config or load_rules()
        self.event = event

    def _detection_gap(self) -> float:
        if self.event is not None:
            return float(self.event.detection_gap_s)
        return float(self.config.detection_gap_s)

    def plan(
        self, state: MPCState, frontier: ParetoFrontier, horizon: int = 10
    ) -> float:
        gap = self._detection_gap()
        if state.gap_ahead_s <= gap:
            return float(frontier.max_energy_mj)
        return float(frontier.max_energy_mj * 0.55)
