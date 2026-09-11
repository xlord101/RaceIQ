"""Pareto frontier: the exchange rate between joules and seconds.

Tier-1 produces, for one circuit, the set of (net energy spent, minimum lap
time) points that are not dominated. Tier-2 and the Overtake EV engine consume
this as a *price list*: "one more MJ buys you this many tenths on this circuit".
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd

__all__ = ["ParetoFrontier"]


class ParetoFrontier:
    """Non-dominated (energy, lap time) points for one lap.

    Attributes
    ----------
    energy_mj:
        Net energy spent over the lap [MJ], ascending.
    lap_time_s:
        Minimum achievable lap time for that energy [s], descending.
    """

    def __init__(self, energy_mj: np.ndarray, lap_time_s: np.ndarray) -> None:
        e = np.asarray(energy_mj, dtype=float)
        t = np.asarray(lap_time_s, dtype=float)
        m = np.isfinite(e) & np.isfinite(t)
        e, t = e[m], t[m]

        if len(e) == 0:
            self.energy_mj = np.zeros(0)
            self.lap_time_s = np.zeros(0)
            return

        # sort by energy, then keep only non-dominated (Pareto) points
        order = np.argsort(e)
        e, t = e[order], t[order]
        best = np.minimum.accumulate(t)
        keep = np.r_[True, best[1:] < best[:-1] - 1e-12]
        self.energy_mj = e[keep]
        self.lap_time_s = best[keep]

    # ------------------------------------------------------------------
    def __len__(self) -> int:
        """Number of points on the frontier."""
        return len(self.energy_mj)

    def is_monotonic(self) -> bool:
        """True when more energy never buys a slower lap (required invariant)."""
        if len(self) < 2:
            return True
        return bool(np.all(np.diff(self.lap_time_s) <= 1e-9))

    @property
    def baseline_time_s(self) -> float:
        """Slowest point on the frontier: the fully-conservative lap."""
        return float(self.lap_time_s[0]) if len(self) else float("nan")

    @property
    def best_time_s(self) -> float:
        """Fastest achievable lap (maximum legal deployment)."""
        return float(self.lap_time_s[-1]) if len(self) else float("nan")

    @property
    def max_energy_mj(self) -> float:
        """Most energy the lap can absorb usefully [MJ]."""
        return float(self.energy_mj[-1]) if len(self) else 0.0

    # ------------------------------------------------------------------
    def time_for_energy(self, energy_mj: float) -> float:
        """Minimum lap time achievable while spending at most ``energy_mj``."""
        if len(self) == 0:
            return float("nan")
        i = int(np.searchsorted(self.energy_mj, energy_mj, side="right") - 1)
        i = int(np.clip(i, 0, len(self) - 1))
        return float(self.lap_time_s[i])

    def energy_for_time(self, lap_time_s: float) -> float:
        """Least energy needed to achieve ``lap_time_s`` [MJ]."""
        if len(self) == 0:
            return float("nan")
        idx = np.flatnonzero(self.lap_time_s <= lap_time_s + 1e-12)
        if len(idx) == 0:
            return float(self.energy_mj[-1])
        return float(self.energy_mj[idx[0]])

    def exchange_rate(self) -> float:
        """Average seconds gained per MJ spent (the price of energy)."""
        if len(self) < 2:
            return 0.0
        de = self.energy_mj[-1] - self.energy_mj[0]
        dt = self.lap_time_s[0] - self.lap_time_s[-1]
        return float(dt / de) if de > 1e-9 else 0.0

    def marginal_rate(self, energy_mj: float) -> float:
        """Local d(time)/d(energy) [s per MJ] around a given spend."""
        if len(self) < 2:
            return 0.0
        i = int(np.clip(np.searchsorted(self.energy_mj, energy_mj), 1, len(self) - 1))
        de = self.energy_mj[i] - self.energy_mj[i - 1]
        dt = self.lap_time_s[i - 1] - self.lap_time_s[i]
        return float(dt / de) if de > 1e-9 else 0.0

    # ------------------------------------------------------------------
    def point_at(self, i: int) -> Tuple[float, float]:
        """``(energy_mj, lap_time_s)`` at index ``i``."""
        return float(self.energy_mj[i]), float(self.lap_time_s[i])

    def as_frame(self) -> pd.DataFrame:
        """Frontier as a tidy DataFrame."""
        return pd.DataFrame(
            {
                "net_energy_mj": self.energy_mj,
                "lap_time_s": self.lap_time_s,
                "delta_vs_baseline_s": self.lap_time_s[0] - self.lap_time_s
                if len(self)
                else np.zeros(0),
            }
        )

    def to_dict(self) -> dict:
        """JSON-serialisable projection."""
        return {
            "energy_mj": [float(x) for x in self.energy_mj],
            "lap_time_s": [float(x) for x in self.lap_time_s],
            "exchange_rate_s_per_mj": self.exchange_rate(),
        }
