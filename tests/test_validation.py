"""Phase 10 tests: the validation suite (spec Section 7).

No public ground-truth SoC exists, so validation is rule closure + predicting
observables. These tests lock in the thresholds the report claims.
"""

import numpy as np
import pytest

from raceiq.validation import (
    baseline_report,
    circuit_ablation,
    clipping_precision_recall,
    pass_auc,
    physics_frontier,
    rule_closure_check,
    run_all,
    synthetic_lap_telemetry,
)


def test_rule_closure_soc_stays_in_window():
    rc = rule_closure_check(n_laps=10)
    assert rc["passed"]
    assert 0.0 <= rc["soc_min"] <= rc["window_mj"]
    assert 0.0 <= rc["soc_max"] <= rc["window_mj"]
    assert rc["harvest_mj"] <= rc["harvest_cap_mj"] + 1e-9
    assert rc["deploy_mj"] <= rc["deploy_allowance_mj"] + 1e-9
    assert rc["ledger_passed"]


def test_rule_closure_reports_no_breaches():
    rc = rule_closure_check(n_laps=5)
    assert rc["breaches"] == []
    assert rc["violations"] == []


def test_clipping_recovers_injected_region():
    cl = clipping_precision_recall(trials=15)
    assert cl["precision"] >= 0.8
    assert cl["recall"] >= 0.6
    assert cl["tp"] > 0


def test_pass_model_auc_beats_target():
    pm = pass_auc(n=2000, seed=1)
    assert pm["auc"] > pm["target_auc"]
    assert 0.0 <= pm["brier"] <= 1.0
    assert pm["passed"]


def test_circuit_ablation_changes_policy():
    ab = circuit_ablation()
    assert ab["posture_changed"]
    assert ab["baku_more_aggressive"]
    assert ab["passed"]


def test_baseline_report_raceiq_wins():
    bl = baseline_report(laps=15, harvest=5.0)
    assert bl["best"] == "RaceIQ"
    assert bl["raceiq_wins"]
    assert bl["raceiq_vs_greedy_s"] > 0
    assert len(bl["rows"]) == 3


def test_physics_frontier_is_monotonic():
    f = physics_frontier(5.0)
    assert len(f) > 1
    assert f.is_monotonic()
    # more energy never buys a slower lap
    assert f.best_time_s <= f.baseline_time_s


def test_synthetic_lap_has_clipping_region():
    tel = synthetic_lap_telemetry(n=120, clip_start=40, clip_end=59)
    assert len(tel) == 120
    assert tel["Throttle"].iloc[50] >= 0.98
    # the pinned region is flat
    seg = tel["Speed"].iloc[40:60].to_numpy()
    assert float(np.ptp(seg)) < 1.0


def test_run_all_returns_every_check():
    rep = run_all(laps=10, harvest=5.0, n_pass_samples=1500)
    for key in ("rule_closure", "clipping", "pass_model", "ablation", "baselines"):
        assert key in rep
        assert "check" in rep[key] or "passed" in rep[key]


def test_observer_calibration_check_runs_or_skips():
    from raceiq.validation.metrics import observer_calibration_check

    res = observer_calibration_check()
    assert res["check"] == "observer_calibration"
    if res.get("skipped"):
        # telemetry not cached in this environment -> graceful skip
        assert "reason" in res
    else:
        assert res["n_laps"] > 0
        assert 0.0 <= res["fitted_duty_mean"] <= 1.0
        # if it ran, it must have matched the observable within tolerance
        assert res["mean_abs_error"] <= res["tol_abs_error"] + 1e-9


def test_run_all_includes_observer_calibration():
    rep = run_all(laps=10, harvest=5.0, n_pass_samples=1500)
    assert "observer_calibration" in rep
    assert rep["observer_calibration"]["check"] == "observer_calibration"
