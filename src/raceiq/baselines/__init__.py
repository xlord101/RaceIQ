"""Baselines: reference strategies RaceIQ is measured against.

Greedy (attack whenever in range) and Conservative (save late, never attack) are
the comparison points; :func:`compare.compare` runs all three on one offline
replay and ranks them by total race time.
"""

from raceiq.baselines.compare import Comparison, RaceIQStrategy, compare
from raceiq.baselines.conservative import ConservativeStrategy
from raceiq.baselines.greedy import GreedyStrategy
from raceiq.baselines.race_sim import RaceSimulator, SimResult, Strategy

__all__ = [
    "RaceSimulator",
    "SimResult",
    "Strategy",
    "GreedyStrategy",
    "ConservativeStrategy",
    "RaceIQStrategy",
    "compare",
    "Comparison",
]
