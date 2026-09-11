"""Head-to-head baseline comparison: RaceIQ vs Greedy vs Conservative.

Runs the same offline race replay under three strategies and returns a table of
results. Per the spec (Sections 8 and 13) this is the evidence that RaceIQ's
Tier-2 MPC beats naive energy management on net time / positions while keeping
the battery healthy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from raceiq.config import EventConfig, RulesConfig, load_rules
from raceiq.baselines.conservative import ConservativeStrategy
from raceiq.baselines.greedy import GreedyStrategy
from raceiq.baselines.race_sim import RaceSimulator, SimResult, Strategy
from raceiq.optimize.frontier import ParetoFrontier
from raceiq.optimize.tier2_mpc import MPCState, Tier2MPC


class RaceIQStrategy:
    """Drive using the Tier-2 MPC posture optimiser."""

    name = "RaceIQ"

    def __init__(
        self,
        frontier: ParetoFrontier,
        config: Optional[RulesConfig] = None,
        event: Optional[EventConfig] = None,
    ) -> None:
        self.frontier = frontier
        self.config = config or load_rules()
        self.event = event
        self._mpc: Optional[Tier2MPC] = None

    def plan(
        self, state: MPCState, frontier: ParetoFrontier, horizon: int = 10
    ) -> float:
        if self._mpc is None:
            self._mpc = Tier2MPC(frontier, config=self.config, event=self.event)
        posture = self._mpc.recommend(state, horizon=horizon)
        return float(posture.per_lap_net_mj[0])


@dataclass
class Comparison:
    """Result of :func:`compare` across all strategies."""

    results: Dict[str, SimResult] = field(default_factory=dict)
    best_strategy: str = ""
    by_total_time: List[str] = field(default_factory=list)

    def as_rows(self) -> List[Dict[str, object]]:
        """Tabular projection (JSON/table friendly)."""
        rows = []
        for name in self.by_total_time:
            r = self.results[name]
            rows.append(
                {
                    "strategy": name,
                    "total_time_s": round(r.total_time_s, 3),
                    "min_soc_mj": round(r.min_soc_mj, 3),
                    "attack_laps": r.attack_laps,
                    "net_position_delta": r.net_position_delta,
                    "final_gap_ahead_s": round(r.final_gap_ahead_s, 3),
                }
            )
        return rows


def compare(
    frontier: ParetoFrontier,
    config: Optional[RulesConfig] = None,
    event: Optional[EventConfig] = None,
    laps: int = 20,
    initial_soc_mj: float = 2.5,
    horizon: int = 10,
    circuit_harvest_potential_mj: float = 3.0,
    **sim_kwargs,
) -> Comparison:
    """Run Greedy, Conservative and RaceIQ on the same replay; rank by time."""
    config = config or load_rules()
    sim = RaceSimulator(
        frontier,
        config,
        circuit_harvest_potential_mj=circuit_harvest_potential_mj,
        **sim_kwargs,
    )

    raceiq = RaceIQStrategy(frontier, config=config, event=event)
    strategies: List[Strategy] = [
        GreedyStrategy(config=config, event=event),
        ConservativeStrategy(config=config, event=event),
        raceiq,
    ]

    results: Dict[str, SimResult] = {}
    for strat in strategies:
        results[strat.name] = sim.simulate(
            strat, laps=laps, initial_soc_mj=initial_soc_mj, horizon=horizon
        )

    ranked = sorted(results.values(), key=lambda r: r.total_time_s)
    return Comparison(
        results={r.name: r for r in results.values()},
        best_strategy=ranked[0].name,
        by_total_time=[r.name for r in ranked],
    )
