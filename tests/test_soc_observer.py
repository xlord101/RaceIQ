"""Phase 2 tests: segmentation, SoC observer, ERS mode and clipping.

The observer is deterministic physics, not a trained model, so what is asserted
here is that it respects the FIA clamps and stays physical - not that it matches
a ground truth nobody publishes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from raceiq.inference import (
    ClippingDetector,
    ErsClassifier,
    SocObserver,
    clipping_flags,
)
from raceiq.physics import (
    brake_energy_mj,
    deploy_gain,
    harvest_energy_mj,
    steady_state_speed_gain,
)
from raceiq.types import Segment, SocState

from conftest import needs_cache


def _segments(rules, n: int = 60) -> list:
    from raceiq.track.segmentation import mark_key_acceleration_zones

    segs = []
    for i in range(n):
        kind = ("straight", "exit", "brake", "coast")[i % 4]
        v_in, v_out = 300.0, 300.0
        harvest = 0.0
        if kind == "brake":
            v_in, v_out = 300.0, 140.0
            harvest = harvest_energy_mj(v_in, v_out, rules.physics)
        segs.append(
            Segment(index=i, start_m=i * 10.0, end_m=(i + 1) * 10.0, kind=kind,
                    mean_speed_kph=0.5 * (v_in + v_out),
                    entry_speed_kph=v_in, exit_speed_kph=v_out,
                    harvest_potential_mj=harvest)
        )
    return mark_key_acceleration_zones(segs, n_zones=2, min_length_m=150.0)


def _lap_frame(rules, n: int = 200) -> pd.DataFrame:
    """A synthetic but physical lap: a fast flat-out straight with brake zones.

    High enough speed and throttle that a full-demand observer drains the
    battery and raises the clipping flag, but with a low-demand setting never
    does. Deterministic (seeded) so the calibration tests are reproducible.
    """
    rng = np.random.default_rng(0)
    dist = np.linspace(0.0, 5000.0, n)
    phase = np.arange(n) % 40
    brake_zone = phase < 6
    speed = np.where(brake_zone, 120.0, 320.0) + rng.normal(0.0, 1.5, n)
    speed = np.clip(speed, 60.0, 340.0)
    throttle = np.where(brake_zone, 0.0, 100.0)
    brake = np.where(brake_zone, 100.0, 0.0)
    t = np.arange(n) * 0.05
    return pd.DataFrame(
        {"Distance": dist, "Speed": speed, "Throttle": throttle, "Brake": brake, "Time": t}
    )


def _frame_segments(frame, rules):
    """Realistic segmentation of `_lap_frame` so the observer behaves physically."""
    from raceiq.track.segmentation import segments_from_telemetry

    return segments_from_telemetry(frame, rules)


# --------------------------------------------------------------------------
# Physics primitives
# --------------------------------------------------------------------------

def test_brake_and_harvest_energy(rules):
    phys = rules.physics
    e = brake_energy_mj(300.0, 100.0, phys["car_mass_kg"])
    assert e > 0
    assert harvest_energy_mj(300.0, 100.0, phys) < e          # never 100% recovery
    assert harvest_energy_mj(300.0, 300.0, phys) == 0.0
    assert harvest_energy_mj(100.0, 300.0, phys) == 0.0       # no free energy


def test_steady_state_speed_gain_is_bounded(rules):
    """The nonlinear drag solve must not predict +70 m/s mid-corner."""
    for v in (80.0, 150.0, 250.0, 330.0):
        dv = steady_state_speed_gain(350.0, v, rules.physics)
        assert dv > 0
        assert dv < v, f"speed gain {dv:.1f} m/s exceeds the base speed at {v} kph"


def test_deploy_gain_monotone_in_power_and_positive_in_energy(rules):
    phys = rules.physics
    prev = -1.0
    for p in (50.0, 150.0, 250.0, 350.0):
        dt, e = deploy_gain(p, 0.2, 200.0, 20.0, phys)
        assert dt > prev, "more power must save more time"
        assert e > 0
        prev = dt
    assert deploy_gain(0.0, 0.2, 200.0, 20.0, phys) == (0.0, 0.0)


def test_deploy_gain_horizon_compounds(rules):
    """A longer horizon must pay back more than a single isolated segment."""
    phys = rules.physics
    dt_short, e = deploy_gain(250.0, 0.14, 250.0, 10.0, phys, horizon_s=0.14)
    dt_long, _ = deploy_gain(250.0, 0.14, 250.0, 10.0, phys, horizon_s=8.0)
    assert dt_long > dt_short > 0.0


# --------------------------------------------------------------------------
# Observer invariants
# --------------------------------------------------------------------------

def test_observer_soc_stays_in_window(rules):
    segs = _segments(rules)
    obs = SocObserver(rules, segs)
    rng = np.random.default_rng(0)
    tel = pd.DataFrame({
        "Distance": np.arange(len(segs)) * 10.0,
        "Speed": rng.uniform(90, 320, len(segs)),
        "Throttle": rng.uniform(0.4, 1.0, len(segs)),
        "Brake": (np.arange(len(segs)) % 4 == 2).astype(float),
    })
    prof = obs.run_lap(tel)
    frame = prof.frame
    assert not frame.empty
    soc = frame["soc_mj"].to_numpy()
    assert np.all(soc >= -1e-9)
    assert np.all(soc <= rules.soc_window_mj + 1e-9)


def test_observer_harvest_never_exceeds_fia_cap(rules):
    segs = _segments(rules)
    obs = SocObserver(rules, segs)
    rng = np.random.default_rng(1)
    tel = pd.DataFrame({
        "Distance": np.arange(len(segs)) * 10.0,
        "Speed": rng.uniform(90, 320, len(segs)),
        "Throttle": rng.uniform(0.4, 1.0, len(segs)),
        "Brake": (np.arange(len(segs)) % 4 == 2).astype(float),
    })
    prof = obs.fit(tel)
    if "harvest_mj" in prof:
        assert prof["harvest_mj"].sum() <= rules.harvest_cap_mj_per_lap + 1e-9


def test_soc_state_percentage_consistency(rules):
    s = SocState.from_soc(1.0, 4.0)
    assert s.soc_pct == pytest.approx(25.0)
    assert SocState.from_soc(99.0, 4.0).soc_pct == pytest.approx(100.0)


# --------------------------------------------------------------------------
# ERS mode + clipping
# --------------------------------------------------------------------------

def test_ers_classifier_labels(rules):
    clf = ErsClassifier(soc_window_mj=rules.soc_window_mj)
    low = SocState.from_soc(0.2, rules.soc_window_mj)
    mid = SocState.from_soc(2.0, rules.soc_window_mj)
    high = SocState.from_soc(3.8, rules.soc_window_mj)
    labels: set = set()
    for s in (low, mid, high):
        labels.add(clf.classify(s, throttle=1.0, speed_kph=250.0))   # full throttle
        labels.add(clf.classify(s, throttle=0.0, brake=1.0, speed_kph=250.0))  # braking
    assert labels <= {"Harvest", "Balance", "Deploy"}
    assert len(labels) >= 2


def test_clipping_needs_full_throttle_and_flat_speed(rules):
    n = 200
    speed = np.concatenate([np.linspace(200, 300, 100), np.full(100, 300.0)])
    throttle = np.ones(n)
    df = pd.DataFrame({"Distance": np.arange(n) * 10.0, "Speed": speed, "Throttle": throttle})
    flags = clipping_flags(df)
    cl = flags["clipping"].to_numpy()
    assert cl[:100].sum() == 0                      # still accelerating
    assert cl[100:].sum() > 0                       # flat at full throttle


def test_clipping_ignores_cars_below_their_own_top_speed(rules):
    """A car merely at terminal velocity in a slow corner is not clipping."""
    n = 120
    # flat speed well below the lap maximum -> aero/grip limited, not clipping
    speed = np.concatenate([np.full(60, 150.0), np.full(60, 320.0)])
    throttle = np.ones(n)
    df = pd.DataFrame({"Distance": np.arange(n) * 10.0, "Speed": speed, "Throttle": throttle})
    flags = clipping_flags(df)
    cl = flags["clipping"].to_numpy()
    assert cl[:60].sum() == 0
    assert cl[60:].sum() > 0


def test_clipping_detector_object(rules):
    det = ClippingDetector()
    assert det is not None
    assert isinstance(det.min_speed_frac_of_max, float)


# --------------------------------------------------------------------------
# Real cached telemetry
# --------------------------------------------------------------------------

@needs_cache
def test_observer_matches_published_harvest(rules, replay):
    """Melbourne brake recovery should land near the published ~2.9 MJ/lap."""
    if replay is None or replay.event != "Melbourne":
        pytest.skip("Melbourne replay not available")
    profiles = replay.profiles
    assert profiles, "no driver profiles"
    harvests = [
        float(p["harvest_mj"].sum()) for p in profiles.values() if "harvest_mj" in p
    ]
    assert harvests
    mean_h = float(np.mean(harvests))
    assert 0.5 * 2.9 < mean_h < 2.0 * 2.9, f"harvest {mean_h:.2f} MJ vs published 2.9"


@needs_cache
def test_field_soc_is_in_window_and_spread(replay, rules):
    if replay is None:
        pytest.skip("no cached replay")
    hist = replay.soc_history()
    if hist.empty:
        pytest.skip("no soc history")
    # Wide frame: one column per driver (plus a leading "lap" column).
    vals = hist.drop(
        columns=[c for c in ("lap",) if c in hist.columns], errors="ignore"
    ).to_numpy(dtype=float)
    assert vals.min() >= -1e-9
    assert vals.max() <= rules.soc_window_mj + 1e-9
    assert vals.max() - vals.min() > 0.05, "field is degenerate"


@needs_cache
def test_observer_does_not_saturate(replay, rules):
    """Every car pinned at 100% would mean the observer is not observing."""
    if replay is None:
        pytest.skip("no cached replay")
    hist = replay.soc_history()
    if hist.empty:
        pytest.skip("no soc history")
    frac = hist.drop(
        columns=[c for c in ("lap",) if c in hist.columns], errors="ignore"
    ).to_numpy(dtype=float) / rules.soc_window_mj
    assert frac.max() <= 0.999, "some car is pinned at a full battery"
    assert frac.min() < 0.95, "no car is ever below 95% - no cycling"


# --------------------------------------------------------------------------
# Calibration: the observer must be ABLE to predict clipping
# --------------------------------------------------------------------------
def test_demand_duty_defaults_to_the_drivers_full_request(rules):
    """Regression: demand duty must not be pre-scaled to what is affordable.

    `duty` used to be the energy-neutral budget (~0.22). Scaling the driver's
    *request* by it made `want > delivered` unreachable, so `clipping_flag` was
    never raised - the observer predicted 0.00% clipping on 36/36 real
    Melbourne laps where ~6.3% is observed.
    """
    ob = SocObserver(rules=rules, segments=_segments(rules))
    assert ob.duty == pytest.approx(1.0), "driver should ask for full deployment"
    assert 0.0 <= ob.sustainable_duty <= 1.0, "sustainable budget is a separate number"


def test_demand_duty_and_sustainable_duty_are_not_conflated(rules):
    """`duty` tracks the driver's demand; `sustainable_duty` does not."""
    ob1 = SocObserver(rules=rules, segments=_segments(rules), aggression=1.0)
    ob2 = SocObserver(rules=rules, segments=_segments(rules), aggression=0.3)
    assert ob1.duty != pytest.approx(ob2.duty), "duty must track the demand"
    assert ob1.sustainable_duty == pytest.approx(
        ob2.sustainable_duty
    ), "sustainable duty is segment-driven, not aggression-driven"


def test_high_demand_produces_clipping(rules):
    """A driver who asks for everything must sometimes be denied."""
    frame = _lap_frame(rules)
    ob = SocObserver(rules=rules, segments=_frame_segments(frame, rules), aggression=1.0)
    res = ob.run_lap(frame)
    assert res.summary["predicted_clip_frac"] > 0.0, (
        "full demand never produced clipping - the demand model is broken"
    )


def test_low_demand_produces_no_clipping(rules):
    """...and one who asks for almost nothing never is."""
    frame = _lap_frame(rules)
    ob = SocObserver(rules=rules, segments=_frame_segments(frame, rules), aggression=0.0)
    res = ob.run_lap(frame)
    assert res.summary["predicted_clip_frac"] == pytest.approx(0.0)


def test_predicted_clipping_increases_with_demand(rules):
    frame = _lap_frame(rules)
    segs = _frame_segments(frame, rules)
    rates = []
    for agg in (0.2, 0.5, 0.8, 1.0):
        ob = SocObserver(rules=rules, segments=segs, aggression=agg)
        rates.append(ob.run_lap(frame).summary["predicted_clip_frac"])
    assert all(b >= a - 1e-9 for a, b in zip(rates, rates[1:])), rates
    assert rates[-1] > rates[0]


def test_summary_reports_both_duties(rules):
    frame = _lap_frame(rules)
    ob = SocObserver(rules=rules, segments=_frame_segments(frame, rules))
    s = ob.run_lap(frame).summary
    assert "duty" in s and "sustainable_duty" in s
    assert "predicted_clip_frac" in s
    assert "predicted_observable_clip_frac" in s
    assert "observed_clip_frac" in s


def test_observable_clip_frac_is_a_fraction(rules):
    frame = _lap_frame(rules)
    ob = SocObserver(rules=rules, segments=_frame_segments(frame, rules))
    s = ob.run_lap(frame).summary
    for key in ("predicted_clip_frac", "predicted_observable_clip_frac",
                "observed_clip_frac"):
        assert 0.0 <= s[key] <= 1.0, key


def test_fit_duty_to_observed_converges(rules):
    """Bisection must improve the match between predicted and observed clipping."""
    frame = _lap_frame(rules)
    segs = _frame_segments(frame, rules)
    ob = SocObserver(rules=rules, segments=segs)
    fit = ob.fit_duty_to_observed(frame)
    assert 0.0 <= fit["duty"] <= 1.0
    assert fit["target"] >= 0.0
    # Calibration must beat leaving the default demand duty untouched.
    baseline = SocObserver(rules=rules, segments=segs).run_lap(frame)
    baseline_err = abs(baseline.summary["predicted_observable_clip_frac"] - fit["target"])
    assert fit["abs_error"] <= baseline_err + 1e-9, (fit, baseline_err)


def test_fit_duty_sets_the_observers_duty(rules):
    frame = _lap_frame(rules)
    ob = SocObserver(rules=rules, segments=_frame_segments(frame, rules))
    fit = ob.fit_duty_to_observed(frame)
    assert ob.duty == pytest.approx(fit["duty"])


def test_fit_duty_is_deterministic(rules):
    frame = _lap_frame(rules)
    segs = _frame_segments(frame, rules)
    a = SocObserver(rules=rules, segments=segs).fit_duty_to_observed(frame)
    b = SocObserver(rules=rules, segments=segs).fit_duty_to_observed(frame)
    assert a["duty"] == pytest.approx(b["duty"])


def test_fit_duty_handles_empty_telemetry(rules):
    ob = SocObserver(rules=rules, segments=_segments(rules))
    fit = ob.fit_duty_to_observed(pd.DataFrame())
    assert fit["duty"] == pytest.approx(ob.duty)
    assert fit["target"] == 0.0


def test_fit_does_not_clobber_the_demand_duty(rules):
    """`fit()` profiles the sustainable plan; it must not disable clipping."""
    frame = _lap_frame(rules)
    ob = SocObserver(rules=rules, segments=_segments(rules))
    before = ob.duty
    ob.fit(frame)
    assert ob.duty == pytest.approx(before), (
        "fit() overwrote the demand duty with the sustainable budget"
    )
    assert 0.0 <= ob.sustainable_duty <= 1.0


def test_observable_mask_marks_the_top_of_the_speed_range():
    from raceiq.inference.soc_observer import _observable_clipping_mask

    tel = pd.DataFrame(
        {
            "Speed": [100.0, 200.0, 300.0, 320.0, 325.0],
            "Throttle": [0.0, 100.0, 100.0, 100.0, 100.0],
        }
    )
    mask = _observable_clipping_mask(tel, throttle_min=0.98, min_speed_frac_of_max=0.90)
    # vmax 325 -> floor 292.5; only 300/320/325 qualify, and 100 kph is off-throttle
    assert mask.tolist() == [False, False, True, True, True]


def test_observable_mask_normalises_percent_throttle():
    from raceiq.inference.soc_observer import _observable_clipping_mask

    tel = pd.DataFrame({"Speed": [300.0, 310.0], "Throttle": [100.0, 55.0]})
    mask = _observable_clipping_mask(tel)
    assert mask.tolist() == [True, False]
