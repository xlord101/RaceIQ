"""Frontend data contract for the RaceIQ broadcast-style pit-wall UI.

This module turns a :class:`~raceiq.ui.scenario.Scenario` into a clean,
JSON-serialisable ``dict`` that a separate animated frontend (built with a tool
such as Antigravity) can consume. The contract is deliberately flat and
framework-agnostic: no pandas / numpy objects, no private attributes, stable
field names.

Every energy / SoC figure here is an **ESTIMATE** - the observer has no ground
truth (no public ERS/SoC telemetry exists). The frontend MUST render the
``meta.watermark`` string at all times (spec Section 3.2).

.. _provenance:

Provenance model (Phase 3)
    Every value the UI renders is labelled with one of three states:

    ``actual``
        Directly sourced session data (positions, running order).
    ``inferred``
        RaceIQ estimates (estimated SoC, ERS mode, belief, decision,
        posture, compliance) - never presented as measured.
    ``counterfactual``
        Projected results (strategy comparison, What-If) - never presented
        as race events.

    Labels are emitted as ``*_provenance`` sidecars on rows plus a top-level
    ``provenance`` block per frame. Nothing outside the closed set
    :data:`PROVENANCE` may be used.

Prior art: arXiv:2603.01290 (cited, framing adopted, implementation original).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from raceiq.ui.scenario import Scenario

__all__ = ["PROVENANCE", "scenario_to_frontend", "write_sample"]


#: The closed provenance taxonomy used by every ``*_provenance`` field in the
#: JSON contract. Values outside this set MUST NOT be emitted (Phase 3).
PROVENANCE: tuple = ("actual", "inferred", "counterfactual")


# --------------------------------------------------------------------------
# Sub-object serializers
# --------------------------------------------------------------------------

def _belief(b: Any) -> Dict[str, Any]:
    return {
        "probs": [float(x) for x in b.probs],
        "p_ers": {k: float(v) for k, v in b.p_ers.items()},
        "p_overtake_available": float(b.p_overtake_available),
        "trap_prob": float(b.trap_prob),
        "trap_flag": bool(b.trap_flag),
        "dominant_ers": b.dominant_ers,
        "evidence": {k: float(v) for k, v in b.evidence.items()},
    }


def _posture(p: Any) -> Dict[str, Any]:
    def _seq(x: Any) -> Any:
        return None if x is None else [float(v) for v in x]
    return {
        "posture": p.posture,
        "expected_value": float(p.expected_value),
        "rationale": p.rationale,
        "horizon_laps": int(p.horizon_laps),
        "per_lap_net_mj": _seq(p.per_lap_net_mj),
        "per_lap_delta_s": _seq(p.per_lap_delta_s),
        "alternatives": {k: float(v) for k, v in p.alternatives.items()},
        "min_soc_mj": float(p.min_soc_mj),
    }


def _compliance(c: Any) -> Dict[str, Any]:
    return {
        "passed": bool(c.passed),
        "violations": list(c.violations),
        "checks": {k: bool(v) for k, v in c.checks.items()},
        "details": {k: str(v) for k, v in c.details.items()},
        "measured": {k: float(v) for k, v in c.measured.items()},
    }


def _driver_row(r: Any) -> Dict[str, Any]:
    return {
        "position": int(r.position),
        # positions/order are the session's source data
        "position_provenance": "actual",
        "driver": r.driver,
        "team": r.team,
        "colour": r.colour,
        "interval_s": float(r.interval_s),
        "lap_delta_s": float(r.lap_delta_s),
        # SoC / ERS mode are always RaceIQ estimates - never measured
        "est_soc_mj": float(r.est_soc_mj),
        "soc_provenance": "inferred",
        "est_soc_pct": float(r.est_soc_pct),
        "mode": r.mode,
        "mode_provenance": "inferred",
    }


def _frontier(f: Any) -> Dict[str, Any]:
    d = f.to_dict()
    d["max_energy_mj"] = float(f.max_energy_mj)
    return d


def _comparison(c: Any) -> Dict[str, Any]:
    rows = []
    for r in c.as_rows():
        # strategy comparisons simulate alternate worlds -> counterfactual
        rows.append({**dict(r), "provenance": "counterfactual"})
    return {
        "best_strategy": c.best_strategy,
        "by_total_time": list(c.by_total_time),
        "rows": rows,
    }


def _frame(d: pd.DataFrame) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for col in d.columns:
        series = d[col]
        if str(series.dtype) == "bool":
            out[col] = [bool(x) for x in series.tolist()]
        elif str(series.dtype).startswith(("int", "float", "uint")):
            out[col] = [float(x) for x in series.tolist()]
        else:
            out[col] = [str(x) for x in series.tolist()]
    return out


def _working(scenario: Scenario) -> Dict[str, Any]:
    """The full calculation chain, so a judge can follow every number.

    This is the "show your working" panel: the model pipeline, the EV formula
    with each term priced, the eligibility test, the trap test, the price of
    energy, the battery estimates and the measured compliance values.
    """
    d = scenario.decision
    b = scenario.belief
    f = scenario.frontier
    bd = d.breakdown
    return {
        "chain": [
            "1. Public telemetry (speed/throttle/brake/distance) -> deterministic SoC observer",
            "2. Rival traces -> 8-state HMM -> P(hidden battery state) + trap test",
            "3. Track segmentation + Tier-1 DP -> Pareto frontier (joules <-> seconds)",
            "4. Tier-2 scenario-tree MPC -> posture for the next 10 laps",
            "5. Overtake EV engine -> GO / HOLD at the Detection Line",
            "6. Compliance ledger -> FIA rule certificate",
        ],
        "ev_formula": (
            "EV = P(pass) x points_gain "
            "- repass_cost - repayment - lambda x illegal"
        ),
        "ev_terms": {
            "p_pass": round(float(d.p_pass), 4),
            "points_gain": round(float(d.points_gain), 4),
            "repass_cost_pts": round(float(bd.get("repass_cost_pts", 0.0)), 4),
            "repayment_pts": round(float(bd.get("repayment_pts", 0.0)), 4),
            "illegal_penalty": round(float(bd.get("illegal_penalty", 0.0)), 4),
            "ev": round(float(d.ev), 4),
        },
        "decision_rule": (
            "GO when EV > 0 AND eligible AND legal AND not trap; "
            "otherwise HOLD. The counter-harvest trap is a hard override."
        ),
        "eligibility": {
            "gap_s": round(float(d.gap_s), 3),
            "detection_gap_s": round(float(scenario.detection_gap_s), 3),
            "eligible": bool(d.eligible),
        },
        "trap_test": {
            "p_Lharvest": round(float(b.p_Lharvest), 4),
            "p_Lderate": round(float(b.p_Lderate), 4),
            "trap_prob": round(float(b.trap_prob), 4),
            "trap_flag": bool(b.trap_flag),
            "p_overtake_available": round(float(b.p_overtake_available), 4),
        },
        "price_of_energy": {
            "exchange_rate_s_per_mj": round(float(f.exchange_rate()), 4),
            "max_energy_mj": round(float(f.max_energy_mj), 4),
            "window_mj": round(float(scenario.window_mj), 4),
        },
        "battery_estimate": {
            "ego_soc_mj": round(float(scenario.ego_row.est_soc_mj), 4),
            "ego_soc_pct": round(float(scenario.ego_row.est_soc_pct), 2),
            "rival_soc_mj": round(float(scenario.rival_row.est_soc_mj), 4),
            "rival_soc_pct": round(float(scenario.rival_row.est_soc_pct), 2),
            "note": "ESTIMATED - no public ERS/SoC telemetry exists",
        },
        "compliance_measured": {
            k: round(float(v), 4) for k, v in scenario.compliance.measured.items()
        },
    }


# --------------------------------------------------------------------------
# Top-level projection
# --------------------------------------------------------------------------

def scenario_to_frontend(scenario: Scenario) -> Dict[str, Any]:
    """Project a full :class:`Scenario` into the JSON frontend contract.

    The returned dict is safe to ``json.dumps`` directly. All numeric values are
    plain ``int``/``float``, lists are Python lists, and every nested object is a
    plain dict with the documented field names.
    """
    return {
        "meta": {
            "event": scenario.event,
            "lap": int(scenario.lap),
            "total_laps": int(scenario.total_laps),
            "window_mj": float(scenario.window_mj),
            "detection_gap_s": float(scenario.detection_gap_s),
            "circuit_harvest_potential_mj": float(scenario.circuit_harvest_potential_mj),
            "ego": scenario.ego,
            "rival": scenario.rival,
            "watermark": scenario.watermark,
            "generated_by": "RaceIQ build_scenario()",
            "prior_art": "arXiv:2603.01290",
            # --- whose pit wall this is ---
            "our_team": scenario.our_team,
            "focus": scenario.focus,
            "teammate": scenario.teammate,
            "our_cars": [
                r.code for r in (scenario.grid.rows if scenario.grid else [])
                if r.is_ours
            ],
            # --- grid provenance (real vs edited vs simulated) ---
            "data_status": (
                scenario.grid.data_status if scenario.grid else "unknown"
            ),
            "simulation_only": bool(
                scenario.grid.simulation_only if scenario.grid else False
            ),
            "grid_edited": bool(scenario.grid.edited if scenario.grid else False),
            "grid_source": scenario.grid.source if scenario.grid else "unknown",
            "grid_note": scenario.grid.note if scenario.grid else "",
        },
        "grid": [
            {**r, "position_provenance": "actual"}
            for r in (scenario.grid.as_rows() if scenario.grid else [])
        ],
        # --- shared provenance model (Phase 3) ---------------------------
        # Positions/order are source data (actual); everything RaceIQ
        # computes is inferred; projections are counterfactual. The UI shows
        # these badges next to the values without re-deriving them.
        "provenance": {
            "frame": "actual",
            "positions": "actual",
            "gaps": "inferred",
            "energy": "inferred",
            "decision": "inferred",
            "belief": "inferred",
            "posture": "inferred",
            "compliance": "inferred",
            "comparison": "counterfactual",
        },
        "working": _working(scenario),
        "tower": [_driver_row(r) for r in scenario.tower],
        "ego_row": _driver_row(scenario.ego_row),
        "rival_row": _driver_row(scenario.rival_row),
        "belief": _belief(scenario.belief),
        "decision": scenario.decision.as_dict(),
        "posture": _posture(scenario.posture),
        "compliance": _compliance(scenario.compliance),
        "compliance_rows": scenario.compliance_rows,
        "frontier": _frontier(scenario.frontier),
        "comparison": _comparison(scenario.comparison),
        "soc_history": _frame(scenario.soc_history),
        "speed_trace": _frame(scenario.speed_trace),
    }


def write_sample(out_dir: str, seed: int = 7, battle_gap_s: float = 0.7) -> List[str]:
    """Write the demo fixtures: five real grids + headline decision frames.

    Produces, for every circuit in ``DEMO_CIRCUITS``:

    * ``grid_<circuit>_real.json``        - the real grid, untouched
    * ``grid_<circuit>_battle.json``      - our car brought into the Detection
      Gap (grid flagged ``edited``) so the bet is live
    * ``grid_<circuit>_battle_trap.json`` - battle + counter-harvest trap

    plus ``sample_scenario.json`` / ``sample_scenario_trap.json`` (Melbourne
    battle), which are the two fixtures referenced by ``FRONTEND_BRIEF.md``.
    """
    from raceiq.ui.grid import DEMO_CIRCUITS
    from raceiq.ui.scenario import build_scenario

    os.makedirs(out_dir, exist_ok=True)
    paths: List[str] = []

    def _dump(name: str, **kw: Any) -> None:
        scen = build_scenario(seed=seed, **kw)
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(scenario_to_frontend(scen), fh, indent=2)
        paths.append(path)

    # Headline decision fixtures used by FRONTEND_BRIEF.md
    _dump("sample_scenario.json", event="Melbourne", focus_gap=battle_gap_s, trap=False)
    _dump("sample_scenario_trap.json", event="Melbourne", focus_gap=battle_gap_s, trap=True)

    # All five demo grids
    for circuit in DEMO_CIRCUITS:
        low = circuit.lower()
        _dump(f"grid_{low}_real.json", event=circuit, trap=False)
        _dump(
            f"grid_{low}_battle.json",
            event=circuit, focus_gap=battle_gap_s, trap=False,
        )
        _dump(
            f"grid_{low}_battle_trap.json",
            event=circuit, focus_gap=battle_gap_s, trap=True,
        )
    return paths


if __name__ == "__main__":  # pragma: no cover - manual utility
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    data_dir = os.path.join(repo_root, "data")
    written = write_sample(data_dir)
    for p in written:
        print("wrote", p)
