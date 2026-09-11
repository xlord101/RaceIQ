"""Phase 5 tests: Overtake EV engine + PassModel.

Covers the priced-bet decision (GO/HOLD), the counter-harvest trap override,
illegal/ineligible gating, circuit-dependent repayment, and PassModel
calibration (the one trained model).
"""

import numpy as np
import pytest

from raceiq.config import load_rules
from raceiq.decision import FEATURE_NAMES, OvertakeContext, OvertakeEV, PassModel
from raceiq.types import Belief


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _belief(p_ld=0.0, p_lh=0.0, p_ot=0.0, trap=False):
    """Build a Belief with chosen marginals (probs normalised for safety)."""
    p_ers = {
        "H": 0.25 - p_ld / 2 - p_lh / 2,
        "M": 0.25 - p_ld / 2 - p_lh / 2,
        "Lharvest": p_lh,
        "Lderate": p_ld,
    }
    for k in p_ers:
        p_ers[k] = max(p_ers[k], 0.0)
    probs = np.array(
        [p_ers["H"], p_ers["H"], p_ers["M"], p_ers["M"],
         p_lh, p_lh, p_ld, p_ld],
        dtype=float,
    )
    probs = probs / probs.sum()
    return Belief(
        probs=probs,
        p_ers=p_ers,
        p_overtake_available=float(p_ot),
        trap_prob=float(p_lh - p_ld),
        trap_flag=bool(trap),
        evidence={},
    )


def _ctx(**kw):
    base = dict(
        gap_ahead_s=0.8,
        closing_speed_kph=15.0,
        straight_remaining_m=400.0,
        own_est_soc=2.0,
        rival_est_soc=2.0,
        belief=_belief(p_ld=0.7, p_lh=0.05, p_ot=0.1, trap=False),
        overtake_mode_active=True,
        circuit_harvest_potential_mj=3.0,
        laps_remaining=10,
        position_before=5,
        legal=True,
    )
    base.update(kw)
    return OvertakeContext(**base)


# --------------------------------------------------------------------------
# Engine decisions
# --------------------------------------------------------------------------
def test_go_when_pass_likely_and_legal():
    ev = OvertakeEV()
    dec = ev.evaluate(_ctx())
    assert dec.go == "GO"
    assert dec.recommendation == "ATTACK"
    assert dec.eligible is True
    assert dec.legal is True
    assert dec.trap_flag is False
    assert 0.0 <= dec.p_pass <= 1.0
    assert dec.ev > 0.0
    assert "GO" in dec.why


def test_trap_forces_hold_regardless_of_ev():
    # Rival looks empty but is actually harvesting (trap) -> must NOT attack.
    ev = OvertakeEV()
    dec = ev.evaluate(
        _ctx(belief=_belief(p_ld=0.05, p_lh=0.7, p_ot=0.8, trap=True))
    )
    assert dec.trap_flag is True
    assert dec.go == "HOLD"
    assert dec.recommendation == "HOLD"
    assert "TRAP" in dec.why


def test_illegal_forces_hold_and_penalty():
    ev = OvertakeEV()
    dec = ev.evaluate(_ctx(legal=False))
    assert dec.legal is False
    assert dec.go == "HOLD"
    assert dec.breakdown["illegal_penalty"] > 0.0
    assert "ILLEGAL" in dec.why


def test_ineligible_when_gap_exceeds_detection():
    ev = OvertakeEV()
    dec = ev.evaluate(_ctx(gap_ahead_s=2.5, detection_gap_s=1.0))
    assert dec.eligible is False
    assert dec.go == "HOLD"


def test_default_points_gain_when_no_position():
    ev = OvertakeEV()
    dec = ev.evaluate(_ctx(position_before=None))
    assert dec.points_gain == pytest.approx(2.0, abs=1e-6)


def test_position_gain_uses_points_table():
    ev = OvertakeEV()
    # P5 -> P4 gain = 10 - 12 = ... wait P5=10, P4=12 -> gain 2
    dec = ev.evaluate(_ctx(position_before=5))
    assert dec.points_gain == pytest.approx(2.0, abs=1e-6)
    # P3 -> P2 gain = 18 - 15 = 3
    dec2 = ev.evaluate(_ctx(position_before=3))
    assert dec2.points_gain == pytest.approx(3.0, abs=1e-6)


def test_repayment_higher_on_low_harvest_circuit():
    """Monza (low harvest) must cost more repayment time than Baku (high)."""
    ev = OvertakeEV()
    monza = ev.evaluate(_ctx(circuit_harvest_potential_mj=3.3))
    baku = ev.evaluate(_ctx(circuit_harvest_potential_mj=7.1))
    assert monza.breakdown["repayment_cost_s"] > baku.breakdown["repayment_cost_s"]


def test_decision_has_full_breakdown_fields():
    ev = OvertakeEV()
    dec = ev.evaluate(_ctx())
    for key in (
        "p_pass",
        "points_gain",
        "repass_cost_pts",
        "repayment_cost_s",
        "repayment_pts",
        "illegal_penalty",
        "ev",
    ):
        assert key in dec.breakdown
        assert isinstance(dec.breakdown[key], float)


def test_as_dict_roundtrip():
    ev = OvertakeEV()
    d = ev.evaluate(_ctx()).as_dict()
    assert d["go"] in ("GO", "HOLD")
    assert "p_pass" in d and "ev" in d


# --------------------------------------------------------------------------
# PassModel calibration
# --------------------------------------------------------------------------
def test_feature_names_count():
    assert len(FEATURE_NAMES) == 12


def test_heuristic_is_deterministic_and_bounded():
    pm = PassModel()
    f = dict(zip(FEATURE_NAMES, [0.5, 20, 400, 0, 2, 2, 0.6, 0.0, 0, 1, 3, 10]))
    a = pm.predict_proba(f)
    b = pm.predict_proba(dict(f))
    assert a == b
    assert 0.0 <= a <= 1.0


def test_fit_runs_and_predicts_in_unit_interval():
    rng = np.random.default_rng(0)
    X, y = [], []
    for _ in range(120):
        gap = rng.uniform(0.1, 2.0)
        y_i = 1 if gap < 0.9 else 0
        X.append([
            gap, 10.0, 300.0, 0.0, 2.0, 2.0,
            0.5 if y_i else 0.05, 0.05 if y_i else 0.5,
            0.0, 1.0, 3.0, 10.0,
        ])
        y.append(y_i)
    pm = PassModel().fit(X, y, groups=[i % 3 for i in range(120)])
    assert pm.trained is True
    for row in X:
        p = pm.predict_proba(dict(zip(FEATURE_NAMES, row)))
        assert 0.0 <= p <= 1.0


def test_fitted_model_ranks_small_gap_above_large():
    rng = np.random.default_rng(1)
    X, y = [], []
    for _ in range(120):
        gap = rng.uniform(0.1, 2.0)
        y_i = 1 if gap < 0.9 else 0
        X.append([
            gap, 10.0, 300.0, 0.0, 2.0, 2.0,
            0.5 if y_i else 0.05, 0.05 if y_i else 0.5,
            0.0, 1.0, 3.0, 10.0,
        ])
        y.append(y_i)
    pm = PassModel().fit(X, y, groups=[i % 4 for i in range(120)])
    small = dict(zip(FEATURE_NAMES, [0.3, 10, 300, 0, 2, 2, 0.5, 0.05, 0, 1, 3, 10]))
    large = dict(zip(FEATURE_NAMES, [1.8, 10, 300, 0, 2, 2, 0.05, 0.5, 0, 1, 3, 10]))
    assert pm.predict_proba(small) > pm.predict_proba(large)


def test_untrained_uses_heuristic():
    pm = PassModel()
    assert pm.trained is False
    p = pm.predict_proba(
        dict(zip(FEATURE_NAMES, [0.4, 20, 400, 0, 2, 2, 0.7, 0.0, 0, 1, 3, 10]))
    )
    assert 0.0 <= p <= 1.0


def test_heuristic_matches_documented_calibration():
    """The heuristic's documented reference case must land near 0.80.

    "0.5 s gap, 10 kph closing, 300 m straight, empty rival ~ 0.8". A positive
    intercept would push every scenario above 0.9 and make the EV engine say GO
    almost unconditionally, so this pins the calibration.
    """
    f = dict(
        gap_ahead_s=0.5, closing_speed_kph=10.0, straight_remaining_m=300.0,
        tyre_age_delta_laps=0.0, own_est_soc=2.0, rival_est_soc=0.5,
        rival_P_Lderate=1.0, rival_P_Lharvest=0.0, trap_flag=0.0,
        overtake_mode_active=0.0, circuit_harvest_potential_mj=3.0,
        laps_remaining=10.0,
    )
    p = PassModel.heuristic_p_pass(f)
    assert 0.70 <= p <= 0.90


def test_heuristic_has_usable_dynamic_range():
    """A hard bet must be clearly less likely than an easy one (not saturated)."""
    easy = dict(
        gap_ahead_s=0.3, closing_speed_kph=25.0, straight_remaining_m=900.0,
        tyre_age_delta_laps=0.0, own_est_soc=3.5, rival_est_soc=0.3,
        rival_P_Lderate=0.9, rival_P_Lharvest=0.05, trap_flag=0.0,
        overtake_mode_active=1.0, circuit_harvest_potential_mj=3.0,
        laps_remaining=10.0,
    )
    hard = dict(easy)
    hard.update(
        gap_ahead_s=1.0, closing_speed_kph=-5.0, straight_remaining_m=150.0,
        own_est_soc=0.4, rival_est_soc=3.5, rival_P_Lderate=0.05,
        rival_P_Lharvest=0.8, overtake_mode_active=0.0,
    )
    pe = PassModel.heuristic_p_pass(easy)
    ph = PassModel.heuristic_p_pass(hard)
    assert pe > 0.85
    assert ph < 0.35
    assert pe - ph > 0.4
