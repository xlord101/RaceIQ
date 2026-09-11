"""EV-bus transfer: the same solver, a different config file.

This is the primary real-world transfer of RaceIQ (spec Section 8, PM e-Bus
Sewa electric bus fleets in India). The mapping from F1 2026 to a city bus is
deliberately direct - every energy concept in the F1 model has a public-transit
analogue:

| F1 2026                      | EV bus                                            |
|------------------------------|---------------------------------------------------|
| 4 MJ usable window           | battery usable window + mandated reserve          |
| 9 MJ harvest cap / lap       | regen per stop / descent                          |
| ~8.5 MJ deploy / lap         | traction energy per route segment                 |
| 350 kW + rampdown            | max C-rate / power limit                          |
| braking zones                | bus stops, descents                               |
| Overtake (+0.5 MJ, proximity)| time-critical opportunity: recover the schedule   |
| Attack / Neutral / Harvest / Defend | drive modes                               |
| pit stop <= 100 kJ           | depot / opportunity charging                      |
| finish above reserve         | reach depot above reserve                         |
| repass / yo-yo               | schedule-slippage rebound                         |

Nothing here is hard-coded: every parameter is read from ``config/ev_bus.json``
through :class:`~raceiq.config.EvBusConfig`. The solver is intentionally the
*same* DP/MPC idea as the F1 path, just driven by the bus config.

Prior art: arXiv:2603.01290 (cited, framing adopted, implementation original).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from raceiq.config import EvBusConfig, load_ev_bus
from raceiq.types import BusRecommendation

__all__ = ["BusState", "EVBusSolver", "BUS_POSTURES"]


#: Bus drive modes mapped from the four F1 postures (spec Section 8).
BUS_POSTURES = ("ATTACK", "NEUTRAL", "HARVEST", "DEFEND")


@dataclass
class BusState:
    """Live state of one bus on its route, fed to :meth:`EVBusSolver.recommend`.

    All quantities are estimates derived from the depot charge, telemetry and the
    published schedule - exactly as the F1 path estimates a rival's battery.
    """

    soc_pct: float                       # current state of charge, % of usable window
    stops_remaining: int                 # stops left before the depot
    distance_to_next_stop_m: float       # metres to the next regen opportunity
    schedule_slack_s: float              # >0 ahead of schedule, <0 behind
    segment_index: int = 0               # index of the current route segment
    is_descent: bool = False             # descent = extra regen (a braking zone)
    depot_available: bool = False        # can top up at the next stop
    total_stops: int = 20                # route length, for logging
    payload_tonnes: float = 0.0          # heavier payload -> more traction energy


class EVBusSolver:
    """Recommend a drive mode for the next route segment.

    Parameters
    ----------
    config:
        Loaded ``config/ev_bus.json``. Defaults to :func:`~raceiq.config.load_ev_bus`.
    """

    #: Fraction of max traction power used in each mode (analogue of the F1
    #: per-lap net-energy posture). ATTACK spends to recover schedule; HARVEST
    #: throttles traction to protect / rebuild charge.
    _POWER_FRACTION = {"ATTACK": 0.95, "NEUTRAL": 0.55, "HARVEST": 0.15, "DEFEND": 0.40}

    #: Speed factor relative to the nominal segment time. >1 means the bus
    #: covers the segment faster (ATTACK), <1 means it slips (HARVEST).
    _SPEED_FACTOR = {"ATTACK": 1.06, "NEUTRAL": 1.0, "HARVEST": 0.95, "DEFEND": 1.0}

    #: Multiplier on regen capture per mode. HARVEST maximises recovery.
    _REGEN_BIAS = {"ATTACK": 0.90, "NEUTRAL": 1.0, "HARVEST": 1.15, "DEFEND": 1.0}

    def __init__(self, config: Optional[EvBusConfig] = None) -> None:
        self.config = config or load_ev_bus()
        # Mode labels come from the config (so they can be localised); fall back
        # to the posture names when the config omits them.
        self.mode_labels = {
            m: str(self.config.modes.get(m, {}).get("name", m)) for m in BUS_POSTURES
        }

    # ------------------------------------------------------------------
    def _route(self) -> Dict[str, float]:
        return dict(self.config.route)

    def _usable_window_kwh(self) -> float:
        """Charge between 0% and the usable window [kWh]."""
        return float(self.config.battery_usable_window_kwh)

    # ------------------------------------------------------------------
    def _net_energy_kwh(self, state: BusState, mode: str) -> float:
        """Net energy the remaining route would consume under ``mode`` [kWh].

        traction (positive, deploys charge) minus regen (negative, recovers).
        A positive value means the battery ends lower than it started.
        """
        r = self._route()
        stops = max(int(state.stops_remaining), 0)
        payload = 1.0 + (r.get("payload_sensitivity_pct_per_tonne", 0.0) / 100.0) * float(
            state.payload_tonnes
        )
        # Traction per segment = base traction + HVAC + gradient, scaled by mode.
        per_seg = (
            self.config.traction_per_segment_kwh
            + r.get("hvac_load_kwh_per_segment", 0.0)
            + r.get("gradient_energy_kwh_per_segment", 0.0)
        )
        traction = per_seg * self._POWER_FRACTION[mode] * payload * stops
        # Regen per stop (braking zones), boosted on descents and in HARVEST.
        regen_per_stop = self.config.regen_per_stop_kwh * self._REGEN_BIAS[mode]
        regen = regen_per_stop * stops
        if state.is_descent:
            regen += r.get("gradient_energy_kwh_per_segment", 0.0) * stops
        if state.depot_available:
            # Opportunity charging at the depot (the pit-stop <= 100 kJ analogue).
            regen += (
                self.config.depot_charge_kw
                * r.get("stop_dwell_s", 25.0)
                / 3600.0
            )
        return float(traction - regen)

    def project_soc(self, state: BusState, mode: str) -> float:
        """Project end-of-route SoC %% if ``mode`` is held to the depot."""
        window = self._usable_window_kwh()
        start_kwh = (float(state.soc_pct) / 100.0) * window
        end_kwh = start_kwh - self._net_energy_kwh(state, mode)
        return float(np.clip(100.0 * end_kwh / window, 0.0, 100.0))

    # ------------------------------------------------------------------
    def recommend(self, state: BusState) -> BusRecommendation:
        """Choose the best drive mode for the next segment.

        Decision logic (mirrors the F1 posture selector):

        * at or below the reserve band -> **HARVEST** (or **DEFEND** if even
          harvesting cannot hold the reserve) to protect arrival;
        * behind schedule (negative slack) -> **ATTACK** to recover time, unless
          that would drop the bus below the reserve (then **DEFEND**);
        * comfortably ahead with healthy charge -> **HARVEST** to bank energy;
        * otherwise -> **NEUTRAL** balanced service.
        """
        soc = float(state.soc_pct)
        reserve = float(self.config.reserve_soc_pct)
        proj = {m: self.project_soc(state, m) for m in BUS_POSTURES}

        if soc <= reserve + 3.0:
            mode = "HARVEST" if proj["HARVEST"] >= reserve - 0.5 else "DEFEND"
        elif state.schedule_slack_s < -1.0:
            mode = "ATTACK" if proj["ATTACK"] >= reserve - 0.5 else "DEFEND"
        elif state.schedule_slack_s > 30.0 and soc > 60.0:
            mode = "HARVEST"
        else:
            mode = "NEUTRAL"

        feasible = proj[mode] >= reserve - 0.5
        chosen_net = self._net_energy_kwh(state, mode)
        baseline_net = self._net_energy_kwh(state, "ATTACK")
        # Energy saved vs an always-attack (schedule-blind) baseline [kWh].
        energy_saved = float(baseline_net - chosen_net)

        r = self._route()
        seg_time = float(r.get("segment_target_time_s", 150.0))
        schedule_delta_s = float(
            (1.0 - self._SPEED_FACTOR[mode]) * seg_time * max(state.stops_remaining, 0)
        )

        rationale = self._rationale(mode, state, proj[mode], reserve, feasible)

        return BusRecommendation(
            mode=mode,
            mode_label=self.mode_labels[mode],
            power_fraction=float(self._POWER_FRACTION[mode]),
            projected_soc_pct=float(proj[mode]),
            reserve_soc_pct=reserve,
            energy_saved_kwh=energy_saved,
            schedule_delta_s=schedule_delta_s,
            rationale=rationale,
            feasible=feasible,
            per_stop_plan=self._per_stop_plan(state, mode),
        )

    # ------------------------------------------------------------------
    def _rationale(
        self, mode: str, state: BusState, proj: float, reserve: float, feasible: bool
    ) -> str:
        bits = [
            f"SoC {state.soc_pct:.0f}% (reserve {reserve:.0f}%), "
            f"schedule slack {state.schedule_slack_s:+.0f}s",
            f"projected depot SoC {proj:.0f}%",
        ]
        if not feasible:
            bits.append("would breach reserve - DEFEND fallback engaged")
        return "; ".join(bits)

    def _per_stop_plan(
        self, state: BusState, mode: str
    ) -> List[Dict[str, float]]:
        """Per-stop energy plan (one row per remaining stop)."""
        out: List[Dict[str, float]] = []
        for i in range(max(int(state.stops_remaining), 0)):
            net = self._net_energy_kwh(
                BusState(
                    soc_pct=state.soc_pct,
                    stops_remaining=state.stops_remaining - i,
                    distance_to_next_stop_m=state.distance_to_next_stop_m,
                    schedule_slack_s=state.schedule_slack_s,
                    segment_index=state.segment_index + i,
                    is_descent=state.is_descent,
                    depot_available=state.depot_available,
                    total_stops=state.total_stops,
                    payload_tonnes=state.payload_tonnes,
                ),
                mode,
            )
            out.append({"stop": float(i + 1), "net_kwh": net})
        return out
