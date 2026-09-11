"""Tier-1 dynamic program: the price list for one lap.

State = ``(segment, SoC bin)``. Action = MGU-K power, filtered by the FIA stack.
The output is the :class:`ParetoFrontier` - minimum lap time for every net
energy spend - which Tier-2 and the Overtake EV engine consume as the exchange
rate between joules and seconds.

Three implementation notes that matter:

**1. Actions are constant shifts.** The energy and time effect of an action
depends only on ``(segment, action)``, never on the state of charge. Every
action is therefore a *constant shift* of the value function and the whole
sweep collapses into a single gather per segment.

**2. The sweep is pre-compiled.** Those shifts are known before the solve
starts, so the per-segment index tables are built once (and cached on
:class:`Tier1DP`); the timed loop contains only the value-function update.

**3. Shifts are integers on a fine grid.** A 10 m segment carries ~0.03 MJ,
which is a third of the spec's 0.1 MJ reporting bin - far too small to
interpolate between bins, and far too small to round to a whole bin without
destroying the energy accounting. So the DP runs on a grid ``oversample``
times finer (0.01 MJ) with *exact integer* shifts, and the frontier is
reported on the coarser public grid. Out-of-window sources fall into the
buffer's sentinel border, which is how illegality is enforced - no branching.

Deployment is only offered where a car would actually deploy (everything except
a braking zone, where the MGU-K is recovering instead), and every power is
clamped by :func:`~raceiq.track.segmentation.max_legal_deploy_kw`, so an
illegal power can never enter the action table.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from raceiq.config import RulesConfig
from raceiq.optimize.frontier import ParetoFrontier
from raceiq.physics import deploy_gain, superclip_penalty_s
from raceiq.track.segmentation import max_legal_deploy_kw
from raceiq.types import DeploymentPlan, PlanSegment, Segment

__all__ = ["solve_lap_dp", "solve_lap_dp_full", "Tier1DP", "LapSolution",
           "phase_durations", "segment_actions"]

#: Sentinel for an unreachable / illegal state. Deliberately astronomically
#: larger than any real lap-time delta (which is a few seconds) so that even a
#: *fraction* of it - as produced when an interpolation straddles the reachable
#: boundary - is still unmistakably infeasible.
_BIG = 1e15

#: A state whose best achievable time exceeds this is not a real state.
_FEASIBLE_MAX = 1e6


# --------------------------------------------------------------------------
# Phases
# --------------------------------------------------------------------------

def phase_durations(segments: Sequence[Segment]) -> np.ndarray:
    """Duration of the acceleration phase enclosing each segment [s].

    A phase runs from the exit of one braking zone to the entry of the next;
    a braking zone is its own phase. Braking resets speed, so speed bought by
    deployment does not carry across a phase boundary - but it *does* carry
    across every segment inside one, which is exactly what
    :func:`~raceiq.physics.deploy_gain` needs as its horizon.
    """
    n = len(segments)
    if n == 0:
        return np.zeros(0)
    out = np.zeros(n, dtype=float)
    i = 0
    while i < n:
        is_brake = segments[i].kind == "brake"
        j = i
        while j < n and (segments[j].kind == "brake") == is_brake:
            j += 1
        total = sum(segments[k].duration_s for k in range(i, j))
        out[i:j] = total
        i = j
    return out


# --------------------------------------------------------------------------
# Action tables
# --------------------------------------------------------------------------

def segment_actions(
    seg: Segment,
    rules: RulesConfig,
    horizon_s: float = 0.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Legal actions for one segment.

    Returns
    -------
    (powers_kw, delta_energy_mj, delta_time_s)
        ``delta_energy_mj`` is positive when energy leaves the battery;
        ``delta_time_s`` is the change in lap time (negative = faster).
        Every ``powers_kw`` entry is a legal MGU-K power for this segment.
    """
    phys = rules.physics
    powers: List[float] = []
    energies: List[float] = []
    times: List[float] = []

    # --- coast: always legal, on every segment ---------------------------
    # Doing nothing must always be available, otherwise a car that reaches a
    # braking zone with a full battery would have no legal action at all and
    # every state would die. Harvesting is optional, not mandatory.
    powers.append(0.0)
    energies.append(0.0)
    times.append(0.0)

    legal_max = max_legal_deploy_kw(seg.mean_speed_kph, seg, rules)

    # --- deployment (never under braking: the MGU-K is recovering there) ----
    if seg.kind != "brake":
        for p in rules.dp_actions_kw:
            if p <= 0:
                continue
            p_eff = min(float(p), legal_max)
            if p_eff <= 1e-9:
                continue
            dt, e = deploy_gain(p_eff, seg.duration_s, seg.mean_speed_kph,
                                seg.length_m, phys, horizon_s=horizon_s)
            if e <= 1e-9 or dt <= 0.0:
                continue
            powers.append(float(p_eff))
            energies.append(float(e))
            times.append(-float(dt))

    # --- harvesting under braking (free: braking is grip-limited) -----------
    if seg.harvest_potential_mj > 1e-6:
        # Display power only: the MGU-K cannot absorb faster than its rated cap,
        # even though a short braking zone concentrates the energy. The actual
        # harvested energy (energies) is the physics-derated potential above.
        harvest_kw = -seg.harvest_potential_mj * 1000.0 / max(seg.duration_s, 1e-6)
        harvest_kw = max(harvest_kw, -rules.mgu_k_max_kw)
        powers.append(float(harvest_kw))
        energies.append(-float(seg.harvest_potential_mj))
        times.append(0.0)

    # --- superclipping: recharge off the ICE at full throttle ---------------
    if seg.kind == "straight":
        p_sc = min(rules.superclip_max_kw, legal_max)
        e_sc = p_sc * seg.duration_s / 1000.0
        if e_sc > 1e-9:
            powers.append(-float(p_sc))
            energies.append(-float(e_sc))
            times.append(float(superclip_penalty_s(e_sc, phys)))

    if not energies:                        # pragma: no cover - defensive
        z = np.zeros(1)
        return z, z.copy(), z.copy()
    return (np.asarray(powers, dtype=float),
            np.asarray(energies, dtype=float),
            np.asarray(times, dtype=float))


@dataclass(frozen=True)
class _Stage:
    """Pre-compiled value-function update for one segment."""

    idx: np.ndarray         # (A, n) int   -> gather index of the source SoC bin
    dt: np.ndarray          # (A, 1)       -> lap-time delta of the action
    powers_kw: np.ndarray   # (A,)         -> requested MGU-K power (NaN = pad)
    shift_bins: np.ndarray  # (A,) int     -> signed SoC change, in grid bins


@dataclass(frozen=True)
class _Program:
    """A compiled lap: everything the timed loop needs and nothing else."""

    stages: Tuple[_Stage, ...]
    pad: int
    n_grid: int             # internal solver grid points
    bin_size: float         # MJ per internal grid step
    n_report: int           # frontier points exposed to callers

    def __len__(self) -> int:
        """Number of stages."""
        return len(self.stages)

    @property
    def n_actions(self) -> int:
        """Actions per stage (uniform after padding)."""
        return len(self.stages[0].powers_kw)


def _compile(
    segments: Sequence[Segment],
    rules: RulesConfig,
    n_report: int,
    oversample: int,
) -> _Program:
    """Build the per-segment shift tables once, outside the timed loop."""
    n_grid = max(int(n_report - 1) * int(oversample), 1) + 1
    bin_size = rules.soc_window_mj / (n_grid - 1)
    horizons = phase_durations(segments)
    tables = [
        segment_actions(seg, rules, horizon_s=float(horizons[i]))
        for i, seg in enumerate(segments)
    ]
    a_max = max(len(t[0]) for t in tables)
    base = np.arange(n_grid)

    # Ending a stage at bin b after a change of `sh` bins means starting it at
    # bin b + sh. Rounding to whole grid steps keeps the gather exact; the grid
    # is fine enough (0.01 MJ) that rounding drift over a lap is ~1-2% of the
    # window, versus ~20% on the 0.1 MJ reporting grid.
    shifts = [np.round(dE / bin_size).astype(np.int64) for _, dE, _ in tables]
    padded = []
    for (powers, dE, dT), sh in zip(tables, shifts):
        # Pad to a uniform action count so the hot loop never branches. Padded
        # actions are priced at +_BIG so they can never win the minimisation.
        k = a_max - len(powers)
        if k:
            powers = np.concatenate([powers, np.full(k, np.nan)])
            sh = np.concatenate([sh, np.zeros(k, dtype=np.int64)])
            dT = np.concatenate([dT, np.full(k, _BIG)])
        padded.append((powers, sh, dT))

    # Border wide enough that an out-of-window source always lands on the
    # sentinel rather than wrapping into a real cell.
    pad = int(max(int(np.abs(sh).max()) for _, sh, _ in padded)) + 2

    stages = [
        _Stage(
            idx=(base[None, :] + sh[:, None] + pad).astype(np.intp),
            dt=dT[:, None],
            powers_kw=powers,
            shift_bins=sh,
        )
        for powers, sh, dT in padded
    ]
    return _Program(tuple(stages), pad, n_grid, bin_size, n_report)


# --------------------------------------------------------------------------
# Result
# --------------------------------------------------------------------------

@dataclass
class LapSolution:
    """Result of one Tier-1 solve."""

    frontier: ParetoFrontier
    solve_ms: float
    segments: int
    actions: int
    power_plan_kw: Optional[np.ndarray] = None
    metadata: Dict[str, float] = field(default_factory=dict)

    @property
    def exchange_rate_s_per_mj(self) -> float:
        """Seconds gained per MJ spent on this circuit."""
        return self.frontier.exchange_rate()


# --------------------------------------------------------------------------
# Solver
# --------------------------------------------------------------------------

def solve_lap_dp(
    segments: Sequence[Segment],
    config: RulesConfig,
    soc_bins: Optional[int] = None,
    start_soc_frac: float = 1.0,
    return_plan: bool = False,
    program: Optional[_Program] = None,
) -> ParetoFrontier:
    """Solve the single-lap energy/time DP.

    Parameters
    ----------
    segments:
        Lap segmentation (10 m segments from :mod:`raceiq.track.segmentation`).
    config:
        Loaded ``rules_2026.json``.
    soc_bins:
        SoC discretisation (default from config, 40 bins over the 4 MJ window).
    start_soc_frac:
        Fraction of the window available at the start of the lap.
    return_plan:
        Attach the recovered power plan to the solution.
    program:
        Pre-compiled stage tables from :func:`precompile`; skips rebuilding.

    Returns
    -------
    ParetoFrontier
    """
    sol = solve_lap_dp_full(
        segments, config, soc_bins=soc_bins,
        start_soc_frac=start_soc_frac, return_plan=return_plan,
        program=program,
    )
    return sol.frontier


def precompile(
    segments: Sequence[Segment],
    config: RulesConfig,
    soc_bins: Optional[int] = None,
) -> _Program:
    """Build (and cache) the stage tables for a circuit.

    Compilation is separated from the solve because it only depends on the
    circuit, not on the state of charge - so Tier-2 can re-solve every lap
    without paying for it again.
    """
    return _compile(
        segments, config,
        int(soc_bins or config.dp_soc_bins),
        int(config.dp.get("solver_oversample", 10)),
    )


def solve_lap_dp_full(
    segments: Sequence[Segment],
    config: RulesConfig,
    soc_bins: Optional[int] = None,
    start_soc_frac: float = 1.0,
    return_plan: bool = False,
    program: Optional[_Program] = None,
) -> LapSolution:
    """Full Tier-1 solve with timing instrumentation (used by validation)."""
    t0 = time.perf_counter()
    if not segments:
        return LapSolution(ParetoFrontier(np.zeros(0), np.zeros(0)), 0.0, 0, 0)

    prog = program if program is not None else precompile(segments, config, soc_bins)
    n, pad, bin_size = prog.n_grid, prog.pad, prog.bin_size
    stages = prog.stages

    F = np.full(n, _BIG, dtype=float)
    start_bin = int(round(np.clip(start_soc_frac, 0.0, 1.0) * (n - 1)))
    F[start_bin] = 0.0

    buf = np.full(n + 2 * pad + 2, _BIG, dtype=float)
    base = np.arange(n)
    take: Optional[np.ndarray] = None
    if return_plan:
        take = np.zeros((len(stages), n), dtype=np.int16)

    for i, st in enumerate(stages):
        buf[pad:pad + n] = F
        cand = buf[st.idx] + st.dt
        if take is None:
            F = cand.min(axis=0)
        else:
            best = np.argmin(cand, axis=0)
            F = cand[best, base]
            take[i] = best.astype(np.int16)

    # Frontier: for each reachable final bin, the least time;
    # net spend = (start - end) bins.
    valid = F < _FEASIBLE_MAX
    if not valid.any():
        return LapSolution(ParetoFrontier(np.zeros(0), np.zeros(0)), 0.0,
                           len(segments), 0)
    end_bins = np.flatnonzero(valid)
    net_mj = (start_bin - end_bins) * bin_size
    times = F[end_bins]

    raw = ParetoFrontier(net_mj, times)
    frontier = _resample(raw, prog.n_report)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    meta = {
        "grid_bin_size_mj": bin_size,
        "grid_points": n,
        "start_bin": start_bin,
        "n_actions_max": prog.n_actions,
        "n_stages": len(stages),
        "max_net_mj": raw.max_energy_mj,
        "exchange_rate_s_per_mj": raw.exchange_rate(),
    }
    plan = None
    if return_plan and take is not None:
        # Trace the quickest reachable lap unless the caller asks otherwise.
        end_bin = int(end_bins[int(np.argmin(times))])
        plan = _recover_plan(take, stages, end_bin)
    return LapSolution(frontier, elapsed_ms, len(segments), prog.n_actions,
                       plan, meta)


def _resample(frontier: ParetoFrontier, n_report: int) -> ParetoFrontier:
    """Project a fine-grid frontier onto the coarser public energy grid."""
    if len(frontier) < 2 or n_report < 2:
        return frontier
    e_max = frontier.max_energy_mj
    if e_max <= 0.0:
        return frontier
    grid = np.linspace(0.0, e_max, int(n_report))
    idx = np.clip(np.searchsorted(frontier.energy_mj, grid, side="right") - 1,
                  0, len(frontier) - 1)
    return ParetoFrontier(grid, frontier.lap_time_s[idx])


def _recover_plan(
    take: np.ndarray,
    stages: Sequence[_Stage],
    end_bin: int,
) -> np.ndarray:
    """Walk the back-pointers backwards from ``end_bin`` to recover the plan.

    Arriving at bin ``b`` after stage ``i`` means having started it at
    ``b + shift``, so the trace steps backwards through the stages.
    """
    n = take.shape[1]
    out = np.full(len(stages), np.nan, dtype=float)
    b = int(np.clip(end_bin, 0, n - 1))
    for i in range(len(stages) - 1, -1, -1):
        st = stages[i]
        a = int(take[i, b])
        out[i] = st.powers_kw[a]
        b = int(np.clip(b + int(st.shift_bins[a]), 0, n - 1))
    return out


def _recover_plan_full(
    take: np.ndarray,
    stages: Sequence[_Stage],
    end_bin: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Like :func:`_recover_plan` but also return the per-stage SoC shift.

    The returned ``shifts`` are the *exact* bin changes the solver used, so the
    recovered plan's energy equals ``shifts * bin_size`` - i.e. it stays inside
    the 4 MJ window by construction. (The displayed ``powers`` are the legal
    MGU-K powers; the energy accounting uses ``shifts`` because the DP rounds
    energy to whole bins to keep the sweep exact.)
    """
    n = take.shape[1]
    powers = np.full(len(stages), np.nan, dtype=float)
    shifts = np.zeros(len(stages), dtype=np.int64)
    b = int(np.clip(end_bin, 0, n - 1))
    for i in range(len(stages) - 1, -1, -1):
        st = stages[i]
        a = int(take[i, b])
        powers[i] = st.powers_kw[a]
        shifts[i] = int(st.shift_bins[a])
        b = int(np.clip(b + shifts[i], 0, n - 1))
    return powers, shifts


class Tier1DP:
    """Object wrapper around :func:`solve_lap_dp` with a cached result.

    Spec signature: ``solve_lap_dp(segments, config, soc_bins=40)``.
    """

    def __init__(self, rules: RulesConfig, segments: Sequence[Segment]) -> None:
        self.rules = rules
        self.segments = list(segments)
        self._solution: Optional[LapSolution] = None
        self._program: Optional[_Program] = None

    @property
    def program(self) -> _Program:
        """Compiled stage tables (built once, reused by every re-solve)."""
        if self._program is None:
            self._program = precompile(self.segments, self.rules)
        return self._program

    def solve(
        self,
        soc_bins: Optional[int] = None,
        start_soc_frac: float = 1.0,
        force: bool = False,
    ) -> LapSolution:
        """Solve (and cache) the frontier for this circuit."""
        if self._solution is None or force or soc_bins is not None:
            self._solution = solve_lap_dp_full(
                self.segments, self.rules, soc_bins=soc_bins,
                start_soc_frac=start_soc_frac,
                program=None if soc_bins else self.program,
            )
        return self._solution

    def _trace(
        self, start_soc_frac: float, target_net_mj: Optional[float] = None
    ) -> Tuple[np.ndarray, int]:
        """Re-run the sweep, returning the back-pointers and the chosen end bin."""
        prog = self.program
        n = prog.n_grid
        start_bin = int(round(np.clip(start_soc_frac, 0.0, 1.0) * (n - 1)))
        take = self._backpointers(start_soc_frac)
        F = np.full(n, _BIG)
        F[start_bin] = 0.0
        buf = np.full(n + 2 * prog.pad + 2, _BIG)
        base = np.arange(n)
        for i, st in enumerate(prog.stages):          # recompute final F
            buf[prog.pad:prog.pad + n] = F
            cand = buf[st.idx] + st.dt
            best = np.argmin(cand, axis=0)
            F = cand[best, base]
        if target_net_mj is None:
            end_bin = int(np.argmin(np.where(F < _FEASIBLE_MAX, F, _BIG)))
        else:
            end_bin = int(np.clip(
                start_bin - round(float(target_net_mj) / prog.bin_size), 0, n - 1))
        return take, end_bin

    def plan(self, start_soc_frac: float = 1.0, target_net_mj: Optional[float] = None
             ) -> np.ndarray:
        """Recovered per-segment power plan [kW] for the quickest reachable lap.

        ``target_net_mj`` picks the plan that spends about that much net energy
        instead. Returns NaN where no action applies.
        """
        take, end_bin = self._trace(start_soc_frac, target_net_mj)
        return _recover_plan(take, self.program.stages, end_bin)

    def deployment_plan(
        self, start_soc_frac: float = 1.0, target_net_mj: Optional[float] = None
    ) -> "DeploymentPlan":
        """Recovered plan as a :class:`DeploymentPlan`.

        The per-segment energies come from the solver's *exact* bin shifts, so the
        plan's net spend is bounded by the 4 MJ window by construction - which is
        what lets it clear the compliance ledger. The displayed ``power_kw`` is the
        legal MGU-K power (already clamped by ``max_legal_deploy_kw``).
        """
        prog = self.program
        take, end_bin = self._trace(start_soc_frac, target_net_mj)
        powers, shifts = _recover_plan_full(take, prog.stages, end_bin)
        segs = self.segments
        plan_segs = []
        for i, seg in enumerate(segs):
            p = 0.0 if np.isnan(powers[i]) else float(powers[i])
            e = float(shifts[i]) * prog.bin_size
            plan_segs.append(
                PlanSegment(
                    segment_index=i,
                    power_kw=p,
                    deploy_mj=max(e, 0.0),
                    harvest_mj=max(-e, 0.0),
                    speed_kph=seg.mean_speed_kph,
                    duration_s=seg.duration_s,
                )
            )
        return DeploymentPlan(segments=plan_segs, lap=5)

    def _backpointers(self, start_soc_frac: float) -> np.ndarray:
        """Re-run the sweep keeping the arg-min at every state."""
        prog = self.program
        n, pad = prog.n_grid, prog.pad
        F = np.full(n, _BIG, dtype=float)
        start_bin = int(round(np.clip(start_soc_frac, 0.0, 1.0) * (n - 1)))
        F[start_bin] = 0.0
        buf = np.full(n + 2 * pad + 2, _BIG, dtype=float)
        base = np.arange(n)
        take = np.zeros((len(prog.stages), n), dtype=np.int16)
        for i, st in enumerate(prog.stages):
            buf[pad:pad + n] = F
            cand = buf[st.idx] + st.dt
            best = np.argmin(cand, axis=0)
            F = cand[best, base]
            take[i] = best.astype(np.int16)
        return take

    @property
    def frontier(self) -> ParetoFrontier:
        """Cached frontier."""
        return self.solve().frontier

    @property
    def last_solve_ms(self) -> float:
        """Wall-clock milliseconds of the last solve."""
        return self.solve().solve_ms

    def exchange_rate(self) -> float:
        """Seconds gained per MJ on this circuit."""
        return self.frontier.exchange_rate()
