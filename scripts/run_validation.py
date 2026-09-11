"""Run the full validation suite (spec Section 7) and print a report.

There is no public ground-truth SoC/ERS label, so the system is validated by
predicting observables (clipping, pass success) plus rule closure. Clipping and
AUC here are scored on *synthetic* data with a known answer - a self-consistency
check that the code recovers a signal we injected. The same code paths run
against cached real telemetry when it is available.

Usage:
    python scripts/run_validation.py
    python scripts/run_validation.py --laps 30 --harvest 5.0

Exit code is 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
import warnings

from raceiq.validation import (
    baseline_report,
    circuit_ablation,
    clipping_precision_recall,
    observer_calibration_check,
    pass_auc,
    rule_closure_check,
)


def main(argv=None) -> int:
    # The pass model is intentionally unscaled (interpretable coefficients);
    # sklearn's lbfgs convergence notes are noise in a report.
    warnings.filterwarnings("ignore")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--laps", type=int, default=20, help="Replay laps")
    parser.add_argument("--harvest", type=float, default=5.0,
                        help="Circuit harvest potential [MJ/lap]")
    parser.add_argument("--samples", type=int, default=3000,
                        help="Synthetic pass-model samples")
    args = parser.parse_args(argv)

    print("=" * 72)
    print("RaceIQ 2026 - validation report")
    print("=" * 72)

    ok = True

    # 1. Rule closure --------------------------------------------------
    rc = rule_closure_check(n_laps=args.laps)
    print("\n[1] Rule closure")
    print(f"    SoC range over {rc['n_laps']} laps : "
          f"{rc['soc_min']:.3f} - {rc['soc_max']:.3f} MJ (window {rc['window_mj']:g})")
    print(f"    harvest / lap             : {rc['harvest_mj']:.3f} MJ "
          f"(cap {rc['harvest_cap_mj']:g})")
    print(f"    deploy  / lap             : {rc['deploy_mj']:.3f} MJ "
          f"(allowance {rc['deploy_allowance_mj']:g})")
    print(f"    compliance ledger         : {'PASS' if rc['ledger_passed'] else 'FAIL'}")
    if rc["violations"]:
        print(f"    violations                : {', '.join(rc['violations'])}")
    print(f"    RESULT                    : {'PASS' if rc['passed'] else 'FAIL'}")
    ok &= bool(rc["passed"])

    # 2. Clipping precision / recall -----------------------------------
    cl = clipping_precision_recall()
    print(f"\n[2] Clipping detection (injected ground truth, {cl['trials']} trials)")
    print(f"    precision {cl['precision']:.3f}   recall {cl['recall']:.3f}   "
          f"F1 {cl['f1']:.3f}")
    print(f"    tp {cl['tp']}  fp {cl['fp']}  fn {cl['fn']}")
    verdict = "PASS" if (cl["precision"] >= 0.8 and cl["recall"] >= 0.6) else "FAIL"
    print(f"    RESULT                    : {verdict}")
    ok &= verdict == "PASS"

    # 3. Pass prediction AUC -------------------------------------------
    pm = pass_auc(n=args.samples)
    print(f"\n[3] Pass prediction (LR, grouped by circuit)")
    print(f"    AUC   {pm['auc']:.3f}  (target > {pm['target_auc']:.2f})")
    print(f"    Brier {pm['brier']:.4f}   train {pm['n_train']} / test {pm['n_test']}")
    print(f"    RESULT                    : {'PASS' if pm['passed'] else 'FAIL'}")
    ok &= bool(pm["passed"])

    # 4. Circuit ablation ----------------------------------------------
    ab = circuit_ablation()
    print("\n[4] Multi-circuit ablation (frontier held fixed, harvest varies)")
    print(f"    Baku  harvest 7.1 -> {ab['baku']['posture']:<9} "
          f"net {ab['baku']['net_mj']:+.3f} MJ")
    print(f"    Monza harvest 3.3 -> {ab['monza']['posture']:<9} "
          f"net {ab['monza']['net_mj']:+.3f} MJ")
    print(f"    posture changed {ab['posture_changed']}   "
          f"Baku more aggressive {ab['baku_more_aggressive']}")
    print(f"    RESULT                    : {'PASS' if ab['passed'] else 'FAIL'}")
    ok &= bool(ab["passed"])

    # 5. Baseline comparison -------------------------------------------
    bl = baseline_report(laps=args.laps, harvest=args.harvest)
    print(f"\n[5] Baseline comparison ({bl['laps']} laps, harvest {bl['harvest_mj']:.1f} MJ)")
    hdr = f"    {'strategy':<14}{'time(s)':>11}{'minSoC':>9}{'atk':>6}{'netPos':>8}{'finGap':>9}"
    print(hdr)
    print("    " + "-" * (len(hdr) - 4))
    for r in bl["rows"]:
        print(f"    {r['strategy']:<14}{r['total_time_s']:>11.2f}"
              f"{r['min_soc_mj']:>9.2f}{r['attack_laps']:>6}"
              f"{r['net_position_delta']:>8}{r['final_gap_ahead_s']:>9.2f}")
    print(f"    RaceIQ advantage vs Greedy: {bl['raceiq_vs_greedy_s']:+.2f} s")
    print(f"    RESULT                    : {'PASS' if bl['raceiq_wins'] else 'FAIL'}")
    ok &= bool(bl["raceiq_wins"])

    # 6. Observer calibration (real telemetry) ----------------------------
    oc = observer_calibration_check()
    print("\n[6] Observer calibration (real telemetry, observable clipping)")
    if oc.get("skipped"):
        print(f"    SKIPPED                   : {oc.get('reason', 'unavailable')}")
    else:
        print(f"    laps calibrated           : {oc['n_laps']}")
        print(f"    fitted demand duty        : {oc['fitted_duty_mean']:.3f} "
              f"(+/- {oc['fitted_duty_std']:.3f})")
        print(f"    mean |pred - obs|         : {oc['mean_abs_error']:.4f} "
              f"(tol {oc['tol_abs_error']:.3f})")
        print(f"    RESULT                    : {'PASS' if oc['passed'] else 'FAIL'}")
        ok &= bool(oc["passed"])

    print("\n" + "=" * 72)
    print(f"OVERALL: {'PASS' if ok else 'FAIL'}")
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
