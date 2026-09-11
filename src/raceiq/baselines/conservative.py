"""Conservative baseline: save the battery, especially in the late laps.

Runs neutral early but switches to full harvest in the final ``save_laps`` laps
and never attacks. It protects the SoC window at the cost of pace - the other
reference point RaceIQ must beat, this time on net race time / positions rather
than battery health.
"""

from __future__ import annotations

from typing import Optional

from raceiq.config import EventConfig, RulesConfig, load_rules
from raceiq.optimize.frontier import ParetoFrontier
from raceiq.optimize.tier2_mpc import MPCState


class ConservativeStrategy:
    """Harvest/save late; never attack."""

    name = "Conservative"

    def __init__(
        self,
        config: Optional[RulesConfig] = None,
        event: Optional[EventConfig] = None,
        save_laps: int = 5,
    ) -> None:
        self.config = config or load_rules()
        self.event = event
        self.save_laps = int(save_laps)

    def plan(
        self, state: MPCState, frontier: ParetoFrontier, horizon: int = 10
    ) -> float:
        if state.laps_remaining <= self.save_laps:
            return float(frontier.max_energy_mj * 0.15)
        return float(frontier.max_energy_mj * 0.55)
