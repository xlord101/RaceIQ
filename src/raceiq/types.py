"""Shared dataclasses used across ingest / inference / rules / optimize / decision.

Kept in one place so that modules never import each other circularly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

# --------------------------------------------------------------------------
# Track
# --------------------------------------------------------------------------

SEGMENT_KINDS = ("brake", "exit", "straight", "coast")


@dataclass(frozen=True)
class Segment:
    """One discretised slice of a lap.

    Attributes
    ----------
    index:
        Zero-based position of the segment within the lap.
    start_m / end_m:
        Distance along the lap centreline, metres.
    kind:
        One of ``brake`` / ``exit`` / ``straight`` / ``coast``.
    mean_speed_kph:
        Mean speed through the segment taken from the observed speed trace.
    entry_speed_kph / exit_speed_kph:
        Speeds at the segment boundaries; used for brake-energy harvesting.
    is_key_acceleration:
        True when the segment lies inside an FIA-designated key acceleration
        zone (350 kW deployment allowed instead of 250 kW).
    harvest_potential_mj:
        Brake energy recoverable in this segment under the 2026 MGU-K-only
        rules. Zero outside braking segments.
    """

    index: int
    start_m: float
    end_m: float
    kind: str
    mean_speed_kph: float
    entry_speed_kph: float
    exit_speed_kph: float
    is_key_acceleration: bool = False
    harvest_potential_mj: float = 0.0

    @property
    def length_m(self) -> float:
        """Segment length in metres."""
        return self.end_m - self.start_m

    @property
    def duration_s(self) -> float:
        """Time to traverse the segment at the observed mean speed."""
        v = max(self.mean_speed_kph / 3.6, 1e-6)
        return self.length_m / v


# --------------------------------------------------------------------------
# Inference
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SocState:
    """Output of the deterministic SoC observer for one telemetry sample.

    ``soc_mj`` is an **estimate** within the FIA 4 MJ usable window.
    """

    soc_mj: float
    mode: str                 # Harvest | Balance | Deploy
    clipping_flag: bool
    harvested_mj: float = 0.0
    deployed_mj: float = 0.0
    soc_pct: float = 0.0      # 0-100 % of the usable window
    distance_m: float = 0.0

    @classmethod
    def from_soc(
        cls,
        soc_mj: float,
        window_mj: float,
        mode: str = "Balance",
        clipping_flag: bool = False,
        **kw: Any,
    ) -> "SocState":
        """Build a :class:`SocState`, computing ``soc_pct`` from the window.

        ``mode`` and ``clipping_flag`` default to neutral values so a caller can
        build a state from just a charge and a window without knowing every
        field - the observer overwrites them with its own estimate afterwards.
        """
        pct = 100.0 * float(np.clip(soc_mj, 0.0, window_mj)) / window_mj
        return cls(
            soc_mj=float(soc_mj),
            mode=mode,
            clipping_flag=clipping_flag,
            soc_pct=float(pct),
            **kw,
        )


@dataclass(frozen=True)
class Belief:
    """Posterior over the 8 hidden opponent states.

    Attributes
    ----------
    probs:
        Length-8 probability vector over
        ``ERS in {H, M, Lharvest, Lderate} x Overtake in {available, spent}``.
    p_ers:
        Marginal over the 4 ERS bins, keyed by ``H``/``M``/``Lharvest``/``Lderate``.
    p_overtake_available:
        P(rival still has Overtake Mode available on the next lap).
    trap_prob:
        P(counter-harvest trap) - rival is *deliberately* saving while running
        low-drag aero, so "looks slow" does **not** mean "is empty".
    """

    probs: np.ndarray
    p_ers: Dict[str, float]
    p_overtake_available: float
    trap_prob: float = 0.0
    trap_flag: bool = False
    evidence: Dict[str, float] = field(default_factory=dict)

    @property
    def p_Lharvest(self) -> float:
        """Probability the rival is deliberately harvesting (trap)."""
        return float(self.p_ers.get("Lharvest", 0.0))

    @property
    def p_Lderate(self) -> float:
        """Probability the rival is genuinely empty (opportunity)."""
        return float(self.p_ers.get("Lderate", 0.0))

    @property
    def dominant_ers(self) -> str:
        """Arg-max ERS bin."""
        return max(self.p_ers, key=self.p_ers.get)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Plans and compliance
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanSegment:
    """Requested MGU-K behaviour for one segment of a candidate plan."""

    segment_index: int
    power_kw: float          # >0 deploy, <0 harvest request (magnitude kW)
    deploy_mj: float = 0.0
    harvest_mj: float = 0.0
    speed_kph: float = 0.0
    duration_s: float = 0.0


@dataclass
class DeploymentPlan:
    """A full-lap candidate energy plan produced by the optimiser."""

    segments: List[PlanSegment] = field(default_factory=list)
    lap: int = 0
    driver: Optional[str] = None
    overtake_mode: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def deploy_mj(self) -> float:
        """Total energy deployed over the lap [MJ]."""
        return float(sum(s.deploy_mj for s in self.segments))

    @property
    def harvest_mj(self) -> float:
        """Total energy harvested over the lap [MJ]."""
        return float(sum(s.harvest_mj for s in self.segments))

    @property
    def net_mj(self) -> float:
        """Net energy spent (deploy minus harvest) [MJ]."""
        return self.deploy_mj - self.harvest_mj

    @property
    def peak_power_kw(self) -> float:
        """Maximum requested MGU-K power [kW]."""
        return float(max((abs(s.power_kw) for s in self.segments), default=0.0))


@dataclass(frozen=True)
class ComplianceResult:
    """Outcome of a rule-ledger check.

    ``passed`` is the AND of every rule; ``violations`` names the failed rules.
    """

    passed: bool
    checks: Dict[str, bool]
    details: Dict[str, str] = field(default_factory=dict)
    measured: Dict[str, float] = field(default_factory=dict)

    @property
    def violations(self) -> List[str]:
        """Names of the rules that failed."""
        return [k for k, v in self.checks.items() if not v]

    def as_rows(self) -> List[Dict[str, str]]:
        """Render as rows for the UI compliance board."""
        return [
            {
                "rule": k,
                "status": "PASS" if v else "FAIL",
                "detail": self.details.get(k, ""),
            }
            for k, v in self.checks.items()
        ]


# --------------------------------------------------------------------------
# Decisions
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Posture:
    """Tier-2 MPC output: the strategic posture for the next stint."""

    posture: str                     # ATTACK | NEUTRAL | HARVEST | DEFEND
    expected_value: float
    rationale: str
    horizon_laps: int = 10
    per_lap_net_mj: Optional[Sequence[float]] = None
    per_lap_delta_s: Optional[Sequence[float]] = None
    alternatives: Dict[str, float] = field(default_factory=dict)
    min_soc_mj: float = 0.0


@dataclass(frozen=True)
class OvertakeDecision:
    """Output of the Overtake EV engine: the priced bet at the detection line."""

    go: str                          # GO | HOLD
    recommendation: str              # ATTACK | HOLD | HARVEST | DEFEND
    p_pass: float
    points_gain: float
    repayment_cost_s: float
    repass_risk: float
    legal: bool
    trap_flag: bool
    eligible: bool
    ev: float
    why: str
    breakdown: Dict[str, float] = field(default_factory=dict)
    gap_s: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        """Plain-dict projection (JSON/table friendly)."""
        return {
            "go": self.go,
            "recommendation": self.recommendation,
            "p_pass": self.p_pass,
            "points_gain": self.points_gain,
            "repayment_cost_s": self.repayment_cost_s,
            "repass_risk": self.repass_risk,
            "legal": self.legal,
            "trap_flag": self.trap_flag,
            "eligible": self.eligible,
            "ev": self.ev,
            "why": self.why,
            "gap_s": self.gap_s,
            **{f"breakdown_{k}": v for k, v in self.breakdown.items()},
        }


@dataclass(frozen=True)
class BusRecommendation:
    """EV-bus transfer output: one drive mode for the next route segment."""

    mode: str                        # ATTACK | NEUTRAL | HARVEST | DEFEND
    mode_label: str
    power_fraction: float
    projected_soc_pct: float
    reserve_soc_pct: float
    energy_saved_kwh: float
    schedule_delta_s: float
    rationale: str
    feasible: bool = True
    per_stop_plan: Optional[Sequence[Dict[str, float]]] = None


__all__ = [
    "SEGMENT_KINDS",
    "Segment",
    "SocState",
    "Belief",
    "PlanSegment",
    "DeploymentPlan",
    "ComplianceResult",
    "Posture",
    "OvertakeDecision",
    "BusRecommendation",
]
