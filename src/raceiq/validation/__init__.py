"""Validation without ground truth (spec Section 7).

No public SoC/ERS labels exist, so RaceIQ is validated by predicting
observables (clipping, pass success) plus rule closure. See
:mod:`raceiq.validation.metrics` for the individual checks.
"""

from raceiq.validation.metrics import (
    baseline_report,
    circuit_ablation,
    clipping_precision_recall,
    observer_calibration_check,
    pass_auc,
    physics_frontier,
    rule_closure_check,
    run_all,
    synthetic_lap_telemetry,
)

__all__ = [
    "rule_closure_check",
    "clipping_precision_recall",
    "pass_auc",
    "circuit_ablation",
    "baseline_report",
    "observer_calibration_check",
    "physics_frontier",
    "synthetic_lap_telemetry",
    "run_all",
]
