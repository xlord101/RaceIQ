"""Tests for clipping / superclipping detection (inference/clipping.py).

These tests also seed the Phase 10 validation harness: we inject a *known*
clipping region into a synthetic lap and measure precision/recall of the
detector against that ground truth. Clipping is the observable that validates
the whole SoC/ERS observer, so it must be exercised thoroughly.
"""

import numpy as np
import pandas as pd
import pytest

from raceiq.inference.clipping import (
    ClippingDetector,
    clipping_events,
    clipping_flags,
    clipping_summary,
)


def _synthetic_lap(n: int = 120, clip_start: int = 40, clip_end: int = 59):
    """Build a lap where samples [clip_start, clip_end] are flat-out at near
    top speed (a known clipping region); everything else is lower-speed full
    or part throttle (not clipping)."""
    rng = np.random.default_rng(0)
    speed = np.full(n, 200.0)
    thr = np.full(n, 1.0)
    # a couple of part-throttle, slower corners so it is not all flat
    speed[:10] = 180.0
    thr[clip_start - 2 : clip_start] = 0.7
    # the clipping straight
    speed[clip_start : clip_end + 1] = 315.0
    # jitter so it is not perfectly flat (but within the delta threshold)
    speed[clip_start : clip_end + 1] += rng.normal(0, 0.1, clip_end - clip_start + 1)
    dist = np.arange(n, dtype=float) * 10.0
    time = np.arange(n, dtype=float) * 0.05
    return pd.DataFrame({"Distance": dist, "Speed": speed, "Throttle": thr, "Time": time})


def test_detector_persistence_needed():
    d = ClippingDetector(min_duration_s=0.25)
    # one isolated clipping sample is not enough (need ~5 x 0.05 s)
    assert d.detect(speed=315.0, throttle=1.0, prev_speed=315.0) is False
    # accumulate: 0.05 s per sample, the last two cross the 0.25 s threshold
    results = [d.detect(speed=315.0, throttle=1.0, prev_speed=315.0) for _ in range(5)]
    assert results[-1] is True
    assert results[-2] is True
    # breaking the condition resets the accumulator
    assert d.detect(speed=200.0, throttle=0.5, prev_speed=200.0) is False
    # and it must re-accumulate from zero afterwards
    assert d.detect(speed=315.0, throttle=1.0, prev_speed=315.0) is False


def test_detector_reset():
    d = ClippingDetector()
    for _ in range(6):
        d.detect(speed=315.0, throttle=1.0, prev_speed=315.0)
    d.reset()
    assert d._elapsed == 0.0
    assert d._prev_speed is None


def test_flags_none_returns_empty():
    out = clipping_flags(None)
    assert isinstance(out, pd.DataFrame)
    assert len(out) == 0


def test_flags_short_input():
    df = pd.DataFrame({"Distance": [0.0, 10.0], "Speed": [200.0, 200.0], "Throttle": [1.0, 1.0]})
    out = clipping_flags(df)
    assert "dSpeed" in out.columns
    assert "clipping" in out.columns
    assert not out["clipping"].any()


def test_flags_scales_throttle_0_100():
    n = 30
    df = pd.DataFrame(
        {
            "Distance": np.arange(n) * 10.0,
            "Speed": np.concatenate([np.full(10, 200.0), np.full(20, 315.0)]),
            "Throttle": np.concatenate([np.full(10, 100.0), np.full(20, 100.0)]),
        }
    )
    out = clipping_flags(df, min_duration_s=0.2)
    # the flat 315 region should be detected even though throttle is 0-100
    assert out["clipping"].any()


def test_flags_uses_time_column():
    n = 40
    df = pd.DataFrame(
        {
            "Distance": np.arange(n) * 10.0,
            "Speed": np.concatenate([np.full(20, 200.0), np.full(20, 315.0)]),
            "Throttle": np.concatenate([np.full(20, 1.0), np.full(20, 1.0)]),
            "Time": np.arange(n) * 0.1,  # 0.1 s cadence -> needs 3 samples
        }
    )
    out = clipping_flags(df, min_duration_s=0.25)
    flagged = out["clipping"].to_numpy()
    # first few of the 315 region are still accumulating; tail must be flagged
    assert flagged[-1]


def test_flags_known_region_precision_recall():
    """Phase 10 seed: detector must recover the injected clipping region."""
    df = _synthetic_lap()
    truth = np.zeros(len(df), dtype=bool)
    truth[40:60] = True
    out = clipping_flags(df)
    pred = out["clipping"].to_numpy()
    tp = int((pred & truth).sum())
    fp = int((pred & ~truth).sum())
    fn = int((~pred & truth).sum())
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    assert precision >= 0.9
    assert recall >= 0.7


def test_summary_empty():
    assert clipping_summary(None)["n_events"] == 0
    empty = pd.DataFrame({"Distance": [], "Speed": [], "clipping": []})
    assert clipping_summary(empty)["n_events"] == 0


def test_summary_no_clipping():
    df = _synthetic_lap()
    df["clipping"] = False
    s = clipping_summary(df)
    assert s["n_events"] == 0
    assert np.isnan(s["entry_speed_kph"])


def test_summary_with_clipping():
    df = _synthetic_lap()
    out = clipping_flags(df)
    s = clipping_summary(out)
    assert s["n_events"] >= 1
    assert s["clipped_distance_m"] > 0.0
    assert 0.0 <= s["clipped_fraction"] <= 1.0
    assert s["entry_speed_kph"] > 0.0


def test_events_contiguous_runs():
    df = _synthetic_lap()
    out = clipping_flags(df)
    ev = clipping_events(out)
    assert len(ev) >= 1
    # each run is a (start, end) with start <= end
    for (a, b) in ev:
        assert a <= b
    # total clipped distance matches the union of event spans
    total = sum(b - a for a, b in ev)
    assert total > 0.0
