"""Optimisation layer: the price of energy.

Tier-1 turns a single lap into a Pareto frontier - the exchange rate between
joules and seconds for that circuit. Tier-2 (see :mod:`raceiq.mpc`) consumes
that frontier over a multi-lap scenario tree.
"""

from raceiq.optimize.frontier import ParetoFrontier
from raceiq.optimize.tier1_dp import LapSolution, Tier1DP, solve_lap_dp, solve_lap_dp_full
from raceiq.optimize.tier2_mpc import MPCState, Tier2MPC

__all__ = [
    "ParetoFrontier",
    "Tier1DP",
    "LapSolution",
    "solve_lap_dp",
    "solve_lap_dp_full",
    "Tier2MPC",
    "MPCState",
]
