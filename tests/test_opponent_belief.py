"""Tests for the 8-state opponent HMM (inference/opponent_belief.py).

Nothing here is trained; the prior is analytic and belief is propagated with the
forward algorithm. These tests exercise the public API and the counter-harvest
trap path.
"""

import numpy as np
import pandas as pd
import pytest

from raceiq.inference.opponent_belief import (
    OpponentBelief,
    compute_emissions,
)


def _belief():
    return OpponentBelief(n_states=8)


def test_prior_sums_to_one():
    b = _belief()
    assert np.isclose(float(b.belief.sum()), 1.0, atol=1e-9)


def test_update_returns_valid_belief():
    b = _belief()
    em = {
        "dv_trap_kph": 5.0,
        "delta_throttle": 0.1,
        "delta_bbrake_m": 0.0,
        "speed_variance": 20.0,
        "zaero": 0,
        "in_aero_zone": True,
    }
    out = b.update(em)
    assert np.isclose(float(out.probs.sum()), 1.0, atol=1e-9)
    assert np.isclose(sum(out.p_ers.values()), 1.0, atol=1e-9)
    assert isinstance(out.trap_flag, bool)
    assert 0.0 <= out.trap_prob <= 1.0


def test_prior_unaffected_before_first_observation():
    b = _belief()
    prior = b.belief.copy()
    _ = b.update({"dv_trap_kph": 1.0, "in_aero_zone": True})
    # the filter state moved, but reset returns the original prior
    b.reset()
    assert np.allclose(b.belief, prior)


def test_emission_likelihood_in_unit_range():
    b = _belief()
    like = b.emission_likelihood(
        {"dv_trap_kph": 0.0, "delta_throttle": 0.0, "delta_bbrake_m": 0.0,
         "speed_variance": 10.0, "zaero": 0}
    )
    assert like.shape == (8,)
    assert like.min() >= 0.0
    assert like.max() <= 1.0


def test_compute_emissions_shape():
    speed = pd.DataFrame(
        {
            "Distance": np.arange(0, 100, 10, dtype=float),
            "Speed": np.concatenate([np.full(5, 200.0), np.full(5, 290.0)]),
            "Throttle": np.concatenate([np.full(5, 1.0), np.full(5, 1.0)]),
        }
    )
    em = compute_emissions(speed, in_aero_zone=True)
    for key in ("dv_trap_kph", "delta_throttle", "delta_bbrake_m",
                "speed_variance", "zaero", "in_aero_zone"):
        assert key in em
    assert em["zaero"] in (0, 1)


def test_aero_zone_emissions_trigger_trap_path():
    """Emissions consistent with a *conserver* rival (slow in the speed trap,
    low throttle-clipping, braking early to lengthen recovery) while running
    low-drag Active Aero must run the counter-harvest trap branch.

    The physics matters: a *fast* rival (positive dv_trap_kph) reads as a
    healthy battery (ERS=H), which is the opposite of a harvesting rival. The
    trap therefore requires a *slow-but-low-drag* signature, and it must only
    fire when both the zaero flag and the aero-zone flag are present.
    """
    conserving = {
        "dv_trap_kph": -5.0,      # slow vs baseline -> conserving, not empty-healthy
        "delta_throttle": 0.18,   # low clipping (Lharvest), far from Lderate's 0.62
        "delta_bbrake_m": -22.0,  # brakes early to lengthen the harvest window
        "speed_variance": 7.0,
    }

    # Aero-zone conserving rival -> trap must fire.
    b = _belief()
    out = None
    for _ in range(6):
        out = b.update({**conserving, "zaero": 1, "in_aero_zone": True})
    assert np.isclose(float(out.probs.sum()), 1.0, atol=1e-9)
    assert out.trap_flag is True
    assert out.p_Lharvest >= 0.45
    assert out.p_Lderate <= out.p_Lharvest - 0.15

    # Identical *Gaussian* signature but without the low-drag aero context:
    # the trap must NOT fire (zaero / in_aero_zone are required conditions).
    b2 = _belief()
    out2 = None
    for _ in range(6):
        out2 = b2.update({**conserving, "zaero": 0, "in_aero_zone": False})
    assert np.isclose(float(out2.probs.sum()), 1.0, atol=1e-9)
    assert out2.trap_flag is False
    # The aero context is what switches the trap on, not the speed signature.
    assert out.trap_flag != out2.trap_flag


def test_batch_runs_over_sequence():
    b = _belief()
    seq = [
        {"dv_trap_kph": 2.0, "in_aero_zone": True},
        {"dv_trap_kph": 3.0, "zaero": 1, "in_aero_zone": True},
        {"dv_trap_kph": 1.0, "in_aero_zone": True},
    ]
    out = b.batch(seq)
    assert np.isclose(float(out.probs.sum()), 1.0, atol=1e-9)


def test_belief_accessors():
    b = _belief()
    out = b.update({"dv_trap_kph": 0.0, "in_aero_zone": True})
    assert 0.0 <= out.p_Lderate <= 1.0
    assert 0.0 <= out.p_Lharvest <= 1.0
    assert 0.0 <= out.p_overtake_available <= 1.0
    assert isinstance(out.dominant_ers, str)


def test_invalid_state_count_rejected():
    with pytest.raises(ValueError):
        OpponentBelief(n_states=4)
