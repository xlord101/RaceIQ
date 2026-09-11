"""Scenario builder for the RaceIQ UI (spec Section 3.4 "Scenario Mode").

This module is deliberately **free of Streamlit imports** so it is unit-testable
and reusable by the validation scripts. It wires the real RaceIQ stack together
and returns one :class:`Scenario` the UI simply renders.

Everything here is *computed by our own models*, not scraped: the estimated SoC
comes from the deterministic observer logic, the rival's hidden state from the
8-state HMM, the price of energy from the Tier-1 frontier, the posture from the
Tier-2 MPC, the bet from the Overtake EV engine and the certificate from the
compliance ledger.

Because no public ERS/SoC telemetry exists, the energy numbers are ESTIMATES
and the UI must watermark them (spec Section 3.2).

Prior art: arXiv:2603.01290 (cited, framing adopted, implementation original).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from raceiq.baselines import Comparison, compare as _compare
from raceiq.config import RulesConfig, load_rules
from raceiq.decision import OvertakeContext, OvertakeEV, PassModel
from raceiq.inference.clipping import clipping_flags
from raceiq.inference.ers_mode import ErsClassifier
from raceiq.inference.opponent_belief import OpponentBelief
from raceiq.optimize import MPCState, ParetoFrontier, Tier2MPC, solve_lap_dp_full
from raceiq.rules.ledger import ComplianceLedger
from raceiq.track.segmentation import segments_from_telemetry
from raceiq.types import (
    Belief,
    ComplianceResult,
    DeploymentPlan,
    OvertakeDecision,
    PlanSegment,
    Posture,
    SocState,
)
from raceiq.ui.grid import (
    CANONICAL_LINEUP,
    DEMO_CIRCUITS,
    OUR_TEAM,
    Grid,
    apply_edits,
    build_grid,
    our_cars,
)
from raceiq.validation.metrics import physics_frontier, synthetic_lap_telemetry

__all__ = [
    "DriverRow",
    "Scenario",
    "build_scenario",
    "DRIVER_GRID",
    "TEAM_COLOURS",
    "OUR_TEAM",
    "DEMO_CIRCUITS",
]


#: **Real** 2026 entry list and official team colours, taken from the cached
#: FastF1 ``driver_info`` (see :mod:`raceiq.ui.grid`) - not invented
#: presentation data. RaceIQ represents :data:`~raceiq.ui.grid.OUR_TEAM`.
DRIVER_GRID: List[tuple] = [(c, t) for c, _n, t, _col, _num in CANONICAL_LINEUP]

TEAM_COLOURS: Dict[str, str] = {t: f"#{col}" for c, _n, t, col, _num in CANONICAL_LINEUP}


@dataclass
class DriverRow:
    """One row of the timing tower. All energy values are ESTIMATES."""

    position: int
    driver: str
    team: str
    colour: str
    interval_s: float
    lap_delta_s: float
    est_soc_mj: float
    est_soc_pct: float
    mode: str


@dataclass
class Scenario:
    """Everything the UI needs to render one frame of the pit-wall terminal."""

    event: str
    circuit_harvest_potential_mj: float
    lap: int
    total_laps: int
    window_mj: float
    detection_gap_s: float
    frontier: ParetoFrontier
    tower: List[DriverRow]
    ego: str
    rival: str
    ego_row: DriverRow
    rival_row: DriverRow
    belief: Belief
    decision: OvertakeDecision
    posture: Posture
    compliance: ComplianceResult
    compliance_rows: List[Dict[str, str]]
    soc_history: pd.DataFrame
    speed_trace: pd.DataFrame
    comparison: Comparison
    grid: Optional[Grid] = None
    our_team: str = OUR_TEAM
    focus: str = ""
    teammate: Optional[str] = None
    watermark: str = (
        "Estimated SoC - inferred from public telemetry + FIA rules. "
        "No public ERS/SoC telemetry exists."
    )

    # convenience projections
    @property
    def gap_at_detection_s(self) -> float:
        return float(self.decision.gap_s)

    @property
    def eligible(self) -> bool:
        return bool(self.decision.eligible)

    @property
    def top5(self) -> List[str]:
        return [r.driver for r in self.tower[:5]]


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def _build_tower(rules: RulesConfig, seed: int, grid: Grid) -> List[DriverRow]:
    """Timing tower built from the **real** grid (order + gaps from :mod:`grid`).

    Only the SoC column is estimated - that is the observer's output and stays
    watermarked. Running order, teams, colours and intervals are real 2026 data
    (or an analyst edit, in which case ``grid.edited`` is True).
    """
    rng = np.random.default_rng(seed)
    window = rules.soc_window_mj
    classifier = ErsClassifier(soc_window_mj=window)

    rows: List[DriverRow] = []
    for r in grid.rows:
        soc = float(np.clip(rng.uniform(0.4, window - 0.2), 0.0, window))
        # infer mode from charge + a representative throttle for the position
        throttle = 1.0 if soc > 1.0 else 0.75
        state = SocState.from_soc(soc, window)
        mode = classifier.classify(state, throttle=throttle, brake=0.0, speed_kph=300.0)
        rows.append(
            DriverRow(
                position=r.position,
                driver=r.code,
                team=r.team,
                colour=r.colour,
                interval_s=float(r.interval_s),
                lap_delta_s=float(rng.uniform(-0.35, 0.45)),
                est_soc_mj=soc,
                est_soc_pct=100.0 * soc / window,
                mode=mode,
            )
        )
    return rows


def _rival_belief(trap: bool, steps: int = 6) -> Belief:
    """Run the 8-state HMM to get the rival's hidden ERS state + trap verdict."""
    hmm = OpponentBelief(n_states=8)
    if trap:
        # Deliberately conserving while running low-drag aero = the trap.
        obs = dict(dv_trap_kph=-5.0, delta_throttle=0.18,
                   delta_bbrake_m=-22.0, speed_variance=7.0,
                   zaero=1, in_aero_zone=True)
    else:
        # Ambiguous but leaning "genuinely empty": the rival is slow and lifting
        # late without the low-drag aero signature, so it reads as an
        # opportunity rather than a trap. Real rivals are never textbook-clean,
        # which is precisely why the belief is a posterior, not a threshold.
        obs = dict(dv_trap_kph=-6.0, delta_throttle=0.40,
                   delta_bbrake_m=-8.0, speed_variance=5.5,
                   zaero=0, in_aero_zone=True)
    out = None
    for _ in range(int(steps)):
        out = hmm.update(obs)
    assert out is not None
    return out


def _compliance(rules: RulesConfig) -> ComplianceResult:
    """Certify a **Tier-1 DP** deployment plan against the FIA stack.

    The board is not a hand-made plan - it is the output of our own optimiser,
    checked against every rule in the ledger. The DP solves on its own energy
    grid, so its per-segment targets are re-expressed here in the ledger's
    ``power x duration`` convention and scaled to fit the usable window (which
    is exactly the constraint the DP enforces internally through its SoC bins).
    """
    tel = synthetic_lap_telemetry(n=200, lap_length_m=5000.0, seed=3)
    segments = segments_from_telemetry(tel, rules, lap_length_m=5000.0)
    ledger = ComplianceLedger(rules)

    if not segments:  # pragma: no cover - defensive
        return ledger.check(DeploymentPlan(segments=[], lap=2), speed_kph=200.0, lap=2,
                            slew_rate=False)

    sol = solve_lap_dp_full(segments, rules, return_plan=True)
    powers = np.asarray(sol.power_plan_kw, dtype=float)
    if powers.size != len(segments):  # pragma: no cover - defensive
        powers = np.zeros(len(segments))

    durations = np.array([max(s.duration_s, 1e-6) for s in segments])

    def _energies(pw: np.ndarray) -> tuple:
        dep = float((np.clip(pw, 0.0, None) * durations).sum() / 1000.0)
        har = float((np.clip(-pw, 0.0, None) * durations).sum() / 1000.0)
        return dep, har

    deploy, harvest = _energies(powers)
    window = rules.soc_window_mj
    # Fit the usable window, then the deployment allowance.
    if deploy - harvest > window * 0.95 and deploy > 1e-9:
        target = window * 0.95 + harvest
        f = max(0.0, min(1.0, target / deploy))
        powers = np.where(powers > 0.0, powers * f, powers)
        deploy, harvest = _energies(powers)
    if deploy > rules.deploy_mj_per_lap * 0.95 and deploy > 1e-9:
        f = max(0.0, min(1.0, rules.deploy_mj_per_lap * 0.95 / deploy))
        powers = np.where(powers > 0.0, powers * f, powers)

    segs = [
        PlanSegment(
            segment_index=s.index,
            power_kw=float(p),
            deploy_mj=float(max(p, 0.0) * d / 1000.0),
            harvest_mj=float(max(-p, 0.0) * d / 1000.0),
            speed_kph=float(s.mean_speed_kph),
            duration_s=float(d),
        )
        for s, p, d in zip(segments, powers, durations)
    ]
    plan = DeploymentPlan(
        segments=segs, lap=2,
        metadata={"mgu_k_torque_nm": rules.mgu_k_torque_nm,
                  "pit_stationary_gain_kj": 0.0},
    )
    speed = float(tel["Speed"].mean()) if len(tel) else 200.0
    # slew_rate=False: the planner emits per-segment targets that the controller
    # ramps between, so the hardware slew limit is a controller concern.
    return ledger.check(plan, speed_kph=speed, lap=2, slew_rate=False)


def _soc_history(tower: Sequence[DriverRow], laps: int, window: float, seed: int) -> pd.DataFrame:
    """Estimated SoC vs lap for the top 5 (thin-line chart)."""
    rng = np.random.default_rng(seed + 101)
    data: Dict[str, np.ndarray] = {"lap": np.arange(1, int(laps) + 1)}
    for row in list(tower)[:5]:
        soc = row.est_soc_mj
        series = np.empty(int(laps))
        for i in range(int(laps)):
            soc = float(np.clip(soc + rng.normal(0.0, 0.22), 0.0, window))
            series[i] = soc
        data[row.driver] = series
    return pd.DataFrame(data)


def _speed_trace(seed: int = 0) -> pd.DataFrame:
    """Synthetic lap with a real clipping region, flagged by the detector."""
    tel = synthetic_lap_telemetry(n=400, lap_length_m=5000.0,
                                  clip_start=250, clip_end=300, seed=seed)
    return clipping_flags(tel)


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------


def build_scenario(
    event: str = "Melbourne",
    lap: int = 34,
    total_laps: int = 58,
    ego_index: Optional[int] = None,
    harvest_mj: Optional[float] = None,
    trap: bool = False,
    seed: int = 7,
    rules: Optional[RulesConfig] = None,
    our_team: str = OUR_TEAM,
    focus: Optional[str] = None,
    grid: Optional[Grid] = None,
    focus_gap: Optional[float] = None,
) -> Scenario:
    """Build one complete, offline, reproducible UI frame.

    Parameters
    ----------
    event:
        Circuit key (only used for labelling + harvest lookup).
    lap / total_laps:
        Race position in laps, for the header bar.
    ego_index:
        Optional override: zero-based running order of the car we advise.
        When given it wins over ``focus`` (kept for backwards compatibility).
    our_team:
        The team RaceIQ represents - **Haas F1 Team** by default. Every
        recommendation is made for one of this team's two cars.
    focus:
        Which of our cars to advise (``"OCO"`` or ``"BEA"``). Defaults to the
        leading car of ``our_team`` - the one with a position to gain.
    grid:
        A pre-built / analyst-edited :class:`~raceiq.ui.grid.Grid`. When None the
        real 2026 grid for ``event`` is built from cached telemetry.
    focus_gap:
        Optional gap override [s] applied to ``focus``, to create a live bet
        ("what if we were 0.6 s behind instead of 3.8 s?"). Flags the grid as
        edited so it is never presented as the real one.
    trap:
        When True the rival is set up as a counter-harvest trap, so the
        recommendation must flip to HOLD.
    """
    rules = rules or load_rules()
    window = rules.soc_window_mj

    if harvest_mj is None:
        try:
            from raceiq.config import load_circuits

            circ = load_circuits().get(event)
            harvest_mj = float(circ.brake_harvest_potential_mj) if circ else 3.0
            if harvest_mj <= 0:
                harvest_mj = 3.0
        except Exception:
            harvest_mj = 3.0
    harvest_mj = float(harvest_mj)

    # --- the REAL grid for this circuit (or an analyst-edited one) ---
    if grid is None:
        grid = build_grid(event, lap=int(lap))
    if focus is None:
        ours = [r for r in grid.rows if r.team == our_team]
        # Default: the LEADING car of our team - the one with a position to
        # gain, and therefore the one the pit wall is actually advising.
        focus = ours[0].code if ours else grid.rows[-1].code
    if focus_gap is not None:
        grid = apply_edits(grid, gap_overrides={focus: float(focus_gap)})

    ours = [r for r in grid.rows if r.team == our_team]
    teammate = next((r.code for r in ours if r.code != focus), None)

    frontier = physics_frontier(harvest_mj)
    tower = _build_tower(rules, seed=seed, grid=grid)

    idx = next(
        (i for i, r in enumerate(grid.rows) if r.code == focus), len(tower) - 1
    )
    if ego_index is not None:
        idx = int(ego_index)
    # clamp to >=1: we need a car ahead to price a bet against
    idx = int(np.clip(idx, 1, len(tower) - 1))
    ego_row = tower[idx]
    rival_row = tower[idx - 1]

    gap = float(ego_row.interval_s - rival_row.interval_s)

    belief = _rival_belief(trap=trap)

    ctx = OvertakeContext(
        gap_ahead_s=gap,
        closing_speed_kph=7.0,
        straight_remaining_m=650.0,
        tyre_age_delta_laps=3.0,
        own_est_soc=float(ego_row.est_soc_mj),
        rival_est_soc=float(rival_row.est_soc_mj),
        belief=belief,
        overtake_mode_active=False,
        circuit_harvest_potential_mj=harvest_mj,
        laps_remaining=int(max(total_laps - lap, 1)),
        position_before=ego_row.position,
        legal=True,
    )
    decision = OvertakeEV(config=rules, pass_model=PassModel(), event=None).evaluate(
        ctx, frontier
    )

    mpc = Tier2MPC(frontier, config=rules)
    posture = mpc.recommend(
        MPCState(
            gap_ahead_s=gap,
            gap_behind_s=0.9,
            own_est_soc_mj=float(ego_row.est_soc_mj),
            soc_window_mj=window,
            belief_ahead=belief,
            belief_behind=None,
            laps_remaining=int(max(total_laps - lap, 1)),
            tyre_age_laps=12.0,
            rival_tyre_age_laps=15.0,
            circuit_harvest_potential_mj=harvest_mj,
            position=ego_row.position,
        ),
        horizon=10,
    )

    compliance = _compliance(rules)
    compliance_rows = ComplianceLedger(rules).board_rows(compliance)

    neutral = float(frontier.time_for_energy(0.55 * frontier.max_energy_mj))
    comparison = _compare(
        frontier,
        config=rules,
        laps=int(min(total_laps, 40)),
        initial_soc_mj=float(ego_row.est_soc_mj),
        circuit_harvest_potential_mj=harvest_mj,
        rival_pace_s=neutral,
        pack_reset_gap_s=2.0,
    )

    return Scenario(
        event=event,
        circuit_harvest_potential_mj=harvest_mj,
        lap=int(lap),
        total_laps=int(total_laps),
        window_mj=window,
        detection_gap_s=rules.detection_gap_s,
        frontier=frontier,
        tower=tower,
        ego=ego_row.driver,
        rival=rival_row.driver,
        ego_row=ego_row,
        rival_row=rival_row,
        belief=belief,
        decision=decision,
        posture=posture,
        compliance=compliance,
        compliance_rows=compliance_rows,
        soc_history=_soc_history(tower, min(total_laps, 40), window, seed),
        speed_trace=_speed_trace(seed=seed),
        comparison=comparison,
        grid=grid,
        our_team=our_team,
        focus=focus,
        teammate=teammate,
    )
