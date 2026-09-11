"""Full-race simulation frames ("racecast") for the animated RaceIQ UI.

This powers the showpiece view: **replay a previous race with all 22 drivers on
that day's real grid**, lap by lap. For every lap the UI gets

* all 22 cars — ESTIMATED SoC, inferred ERS mode, position, interval and a live
  telemetry sample (speed / throttle / brake / clipping) for the hover card;
* the two **Haas** cars pinned with extra detail — the live **risk / reward
  ratio**, the priced bet (P(pass), EV) and the recommended **action**
  (ATTACK / HOLD / HARVEST / DEFEND).

Everything energy-related is an ESTIMATE (no public ERS/SoC telemetry exists) and
must be rendered with the watermark.

Prior art: arXiv:2603.01290 (cited, framing adopted, implementation original).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from raceiq.config import RulesConfig, load_rules
from raceiq.decision import OvertakeContext, OvertakeEV, PassModel
from raceiq.inference.clipping import clipping_flags
from raceiq.inference.ers_mode import ErsClassifier
from raceiq.optimize import ParetoFrontier
from raceiq.types import SocState
from raceiq.ui.grid import OUR_TEAM, build_grid, circuit_status, real_pace, our_cars
from raceiq.validation.metrics import physics_frontier, synthetic_lap_telemetry

__all__ = ["CarFrame", "HaasFrame", "LapFrame", "RaceCast", "build_racecast"]


#: Fraction of a circuit's brake-harvest potential the MGU-K actually recovers.
_HARVEST_EFFICIENCY = 0.55


@dataclass
class CarFrame:
    """One car's state on one lap — this is what the hover card shows."""

    code: str
    name: str
    team: str
    colour: str
    number: str
    position: int
    interval_s: float
    gap_ahead_s: float
    est_soc_mj: float
    est_soc_pct: float
    mode: str
    speed_kph: float
    throttle: float
    brake: float
    clipping: bool
    lap_time_s: float
    is_ours: bool


@dataclass
class HaasFrame:
    """Pinned Haas car: everything in :class:`CarFrame` plus the live decision."""

    code: str
    team: str
    colour: str
    position: int
    interval_s: float
    gap_ahead_s: float
    est_soc_mj: float
    est_soc_pct: float
    mode: str
    speed_kph: float
    throttle: float
    # --- the priced bet ---
    action: str  # ATTACK | HOLD | HARVEST | DEFEND
    go: str  # GO | HOLD
    eligible: bool
    p_pass: float
    ev: float
    reward_pts: float  # expected points gained  = P(pass) x points
    risk_pts: float  # expected cost          = repass + repayment
    risk_reward: Optional[float]  # reward / risk  (None when risk is 0)
    trap_flag: bool
    rationale: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "team": self.team,
            "colour": self.colour,
            "position": self.position,
            "interval_s": round(self.interval_s, 3),
            "gap_ahead_s": round(self.gap_ahead_s, 3),
            "est_soc_mj": round(self.est_soc_mj, 3),
            "est_soc_pct": round(self.est_soc_pct, 2),
            "mode": self.mode,
            "speed_kph": round(self.speed_kph, 1),
            "throttle": round(self.throttle, 3),
            "action": self.action,
            "go": self.go,
            "eligible": self.eligible,
            "p_pass": round(self.p_pass, 4),
            "ev": round(self.ev, 4),
            "reward_pts": round(self.reward_pts, 4),
            "risk_pts": round(self.risk_pts, 4),
            "risk_reward": (
                None if self.risk_reward is None else round(self.risk_reward, 3)
            ),
            "trap_flag": self.trap_flag,
            "rationale": self.rationale,
        }


@dataclass
class LapFrame:
    """One lap of the race: all 22 cars + the pinned Haas pair."""

    lap: int
    cars: List[CarFrame]
    haas: List[HaasFrame]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "lap": self.lap,
            "cars": [c.__dict__ | {"est_soc_mj": round(c.est_soc_mj, 3),
                                   "est_soc_pct": round(c.est_soc_pct, 2),
                                   "interval_s": round(c.interval_s, 3),
                                   "gap_ahead_s": round(c.gap_ahead_s, 3),
                                   "speed_kph": round(c.speed_kph, 1),
                                   "throttle": round(c.throttle, 3),
                                   "lap_time_s": round(c.lap_time_s, 3)}
                     for c in self.cars],
            "haas": [h.as_dict() for h in self.haas],
        }


@dataclass
class RaceCast:
    """A complete simulated replay for one circuit."""

    circuit: str
    total_laps: int
    our_team: str
    laps: List[LapFrame]
    data_status: str
    simulation_only: bool
    watermark: str = (
        "Estimated SoC - inferred from public telemetry + FIA rules. "
        "No public ERS/SoC telemetry exists."
    )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "circuit": self.circuit,
            "total_laps": self.total_laps,
            "our_team": self.our_team,
            "data_status": self.data_status,
            "simulation_only": self.simulation_only,
            "watermark": self.watermark,
            "prior_art": "arXiv:2603.01290",
            "laps": [f.as_dict() for f in self.laps],
        }


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _telemetry_trace(circuit: str, seed: int = 7) -> pd.DataFrame:
    """A representative speed/throttle/clipping trace for the circuit.

    Prefers real cached telemetry; falls back to the synthetic lap. Used to give
    the hover card a believable live telemetry readout.
    """
    try:
        from raceiq.ingest.fastf1_loader import get_lap_telemetry, load_fastf1_session

        data = load_fastf1_session(
            2026, circuit, "R", with_telemetry=True, allow_openf1_fallback=False
        )
        laps = getattr(data, "laps", None)
        if laps is not None and len(laps):
            counts = laps.groupby("Driver").size().sort_values(ascending=False)
            for drv in counts.index:
                tel = get_lap_telemetry(data, str(drv), resample_m=25.0)
                if len(tel) > 50:
                    return clipping_flags(tel)
    except Exception:  # pragma: no cover - offline / no session
        pass
    return clipping_flags(synthetic_lap_telemetry(n=400, lap_length_m=5000.0, seed=seed))


def _sample_telemetry(trace: pd.DataFrame, phase: float, rng: np.random.Generator):
    """Sample the trace at ``phase`` (0-1 of the lap) with small lap-to-lap noise."""
    n = len(trace)
    if n == 0:  # pragma: no cover - defensive
        return 200.0, 0.8, 0.0, False
    i = int(np.clip(phase, 0.0, 1.0) * (n - 1))
    row = trace.iloc[i]
    speed = float(row.get("Speed", 200.0)) + float(rng.normal(0, 2.0))
    thr = float(row.get("Throttle", 0.8))
    if thr > 1.5:
        thr /= 100.0
    thr = float(np.clip(thr + rng.normal(0, 0.03), 0.0, 1.0))
    brake = float(row.get("Brake", 0.0) or 0.0)
    clip = bool(row.get("clipping", False))
    return max(speed, 0.0), thr, brake, clip


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------

def build_racecast(
    circuit: str = "Melbourne",
    total_laps: Optional[int] = None,
    seed: int = 7,
    rules: Optional[RulesConfig] = None,
    frontier: Optional[ParetoFrontier] = None,
) -> RaceCast:
    """Simulate a full race for ``circuit`` on that day's real grid.

    Returns one :class:`LapFrame` per lap with all 22 cars plus the pinned Haas
    pair (risk / reward + action).
    """
    rules = rules or load_rules()
    window = rules.soc_window_mj
    rng = np.random.default_rng(seed)

    grid = build_grid(circuit, lap=1)
    pace = real_pace(circuit)
    data_status, sim_only = circuit_status(circuit)

    from raceiq.config import load_circuits

    circ = load_circuits().get(circuit)
    harvest_potential = float(getattr(circ, "brake_harvest_potential_mj", 3.0) or 3.0)
    if total_laps is None:
        total_laps = int(getattr(circ, "total_laps", 0) or 58)
    total_laps = int(max(total_laps, 1))

    if frontier is None:
        frontier = physics_frontier(harvest_potential)

    trace = _telemetry_trace(circuit, seed=seed)
    classifier = ErsClassifier(soc_window_mj=window)
    ev_engine = OvertakeEV(config=rules, pass_model=PassModel(), event=None)

    # --- starting state -------------------------------------------------
    codes = [r.code for r in grid.rows]
    base_pace = np.array(
        [float(pace.get(c, 0.0)) or float(np.median(list(pace.values()))) if pace else 90.0
         for c in codes]
    )
    if not np.any(base_pace > 0):  # pragma: no cover - no telemetry
        base_pace = np.linspace(90.0, 95.0, len(codes))
    median_pace = float(np.median(base_pace))

    # faster cars deploy harder; slower cars harvest to stay in the race
    aggression = np.clip((median_pace - base_pace) / max(median_pace, 1e-6) * 4.0 + 0.5,
                         0.15, 0.95)
    soc = np.full(len(codes), 0.55 * window, dtype=float)
    cumulative = np.zeros(len(codes), dtype=float)

    haas_codes = [r.code for r in our_cars(grid)]
    if not haas_codes:  # pragma: no cover - defensive
        haas_codes = [grid.rows[0].code]

    frames: List[LapFrame] = []
    for lap in range(1, total_laps + 1):
        # --- energy: harvest is circuit-limited, deploy follows aggression ---
        harvest = harvest_potential * _HARVEST_EFFICIENCY
        # A car cannot sustainably deploy more than it harvests: over a stint the
        # budget must balance. Aggression tilts the net spend negative (attacking)
        # or positive (banking), but never by more than the harvest allows.
        k = 0.78 + aggression * 0.42  # 0.84 .. 1.18
        deploy = np.minimum(harvest * k, rules.deploy_mj_per_lap)
        net = harvest - deploy
        soc = np.clip(soc + net + rng.normal(0, 0.04, len(soc)), 0.0, window)

        # --- lap times + cumulative gaps from real pace ---
        lap_times = base_pace + rng.normal(0, 0.12, len(codes)) - (deploy * 0.12)
        cumulative = cumulative + lap_times
        order = np.argsort(cumulative)
        leader_time = cumulative[order[0]]

        car_frames: List[CarFrame] = []
        haas_frames: List[HaasFrame] = []

        for rank, idx in enumerate(order):
            row = grid.rows[idx]
            interval = float(cumulative[idx] - leader_time)
            gap_ahead = 0.0 if rank == 0 else float(
                cumulative[idx] - cumulative[order[rank - 1]]
            )
            phase = float(((lap * 0.37) + idx * 0.041) % 1.0)
            speed, thr, brake, clip = _sample_telemetry(trace, phase, rng)

            state_soc = float(soc[idx])
            mode = classifier.classify(
                SocState.from_soc(state_soc, window),
                throttle=thr,
                brake=brake,
                speed_kph=speed,
            )

            car_frames.append(
                CarFrame(
                    code=row.code,
                    name=row.name,
                    team=row.team,
                    colour=row.colour,
                    number=row.number,
                    position=rank + 1,
                    interval_s=interval,
                    gap_ahead_s=gap_ahead,
                    est_soc_mj=state_soc,
                    est_soc_pct=100.0 * state_soc / window,
                    mode=mode,
                    speed_kph=speed,
                    throttle=thr,
                    brake=brake,
                    clipping=clip,
                    lap_time_s=float(lap_times[idx]),
                    is_ours=row.is_ours,
                )
            )

            # --- pinned Haas car: price the bet on this lap ---
            if row.code in haas_codes and rank > 0:
                rival_idx = order[rank - 1]
                ctx = OvertakeContext(
                    gap_ahead_s=gap_ahead,
                    closing_speed_kph=max(speed - 250.0, 0.0),
                    straight_remaining_m=650.0,
                    tyre_age_delta_laps=float(lap % 20) * 0.2,
                    own_est_soc=state_soc,
                    rival_est_soc=float(soc[rival_idx]),
                    belief=None,
                    overtake_mode_active=False,
                    circuit_harvest_potential_mj=harvest_potential,
                    laps_remaining=max(total_laps - lap, 1),
                    position_before=rank + 1,
                    legal=True,
                )
                dec = ev_engine.evaluate(ctx, frontier)
                reward = float(dec.p_pass * dec.points_gain)
                risk = float(
                    dec.breakdown.get("repass_cost_pts", 0.0)
                    + dec.breakdown.get("repayment_pts", 0.0)
                )
                ratio = (reward / risk) if risk > 1e-9 else None
                haas_frames.append(
                    HaasFrame(
                        code=row.code,
                        team=row.team,
                        colour=row.colour,
                        position=rank + 1,
                        interval_s=interval,
                        gap_ahead_s=gap_ahead,
                        est_soc_mj=state_soc,
                        est_soc_pct=100.0 * state_soc / window,
                        mode=mode,
                        speed_kph=speed,
                        throttle=thr,
                        action=dec.recommendation,
                        go=dec.go,
                        eligible=bool(dec.eligible),
                        p_pass=float(dec.p_pass),
                        ev=float(dec.ev),
                        reward_pts=reward,
                        risk_pts=risk,
                        risk_reward=ratio,
                        trap_flag=bool(dec.trap_flag),
                        rationale=dec.why,
                    )
                )

        frames.append(LapFrame(lap=lap, cars=car_frames, haas=haas_frames))

    return RaceCast(
        circuit=circuit,
        total_laps=total_laps,
        our_team=OUR_TEAM,
        laps=frames,
        data_status=data_status,
        simulation_only=sim_only,
    )


def write_racecast(out_dir: str, circuits: Sequence[str] = ("Melbourne",),
                   seed: int = 7) -> List[str]:
    """Write ``racecast_<circuit>.json`` for each circuit."""
    os.makedirs(out_dir, exist_ok=True)
    paths: List[str] = []
    for c in circuits:
        rc = build_racecast(c, seed=seed)
        path = os.path.join(out_dir, f"racecast_{c.lower()}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rc.as_dict(), fh, indent=1)
        paths.append(path)
    return paths


if __name__ == "__main__":  # pragma: no cover - manual utility
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(here, "..", "..", ".."))
    for p in write_racecast(os.path.join(repo, "data"),
                            ("Melbourne", "Shanghai", "Monza")):
        print("wrote", p)
