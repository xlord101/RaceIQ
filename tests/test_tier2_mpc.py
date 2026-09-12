"""Phase 6 tests: Tier-2 MPC posture optimiser.

Covers the four-way posture choice, the Baku-vs-Monza circuit ablation (the spec
requires the policy to *change* with harvest potential), trap avoidance, and
low-battery reserve building.
"""

import numpy as np
import pytest

from raceiq.config import load_rules
from raceiq.optimize import MPCState, ParetoFrontier, Tier2MPC
from raceiq.types import Belief

POSTURES = ("ATTACK", "NEUTRAL", "HARVEST", "DEFEND")


def _frontier():
    # Synthetic but monotone frontier: more net energy -> faster lap.
    energy = np.array([0.0, 2.0, 4.0, 6.0, 8.0])
    times = np.array([92.0, 90.5, 89.5, 89.0, 88.7])
    return ParetoFrontier(energy, times)


def _belief(trap=False, p_ld=0.0, p_lh=0.0, p_ot=0.0):
    p_ers = {
        "H": 0.25 - p_ld / 2 - p_lh / 2,
        "M": 0.25 - p_ld / 2 - p_lh / 2,
        "Lharvest": p_lh,
        "Lderate": p_ld,
    }
    for k in p_ers:
        p_ers[k] = max(p_ers[k], 0.0)
    probs = np.array([p_ers["H"], p_ers["H"], p_ers["M"], p_ers["M"],
                     p_lh, p_lh, p_ld, p_ld], dtype=float)
    probs = probs / probs.sum()
    return Belief(
        probs=probs, p_ers=p_ers, p_overtake_available=p_ot,
        trap_prob=float(p_lh - p_ld), trap_flag=trap, evidence={},
    )


def _state(**kw):
    base = dict(
        gap_ahead_s=1.0, gap_behind_s=1.0, own_est_soc_mj=4.0, soc_window_mj=4.0,
        belief_ahead=None, belief_behind=None, laps_remaining=10,
        tyre_age_laps=10.0, rival_tyre_age_laps=10.0,
        circuit_harvest_potential_mj=5.0, position=None,
    )
    base.update(kw)
    return MPCState(**base)


# --------------------------------------------------------------------------
def test_recommend_returns_valid_posture():
    mpc = Tier2MPC(_frontier())
    dec = mpc.recommend(_state(circuit_harvest_potential_mj=5.0))
    assert dec.posture in POSTURES
    assert isinstance(dec.expected_value, float)
    assert dec.horizon_laps == 10
    assert len(dec.per_lap_net_mj) == 10
    assert len(dec.per_lap_delta_s) == 10
    assert set(dec.alternatives.keys()) == set(POSTURES)


def test_circuit_ablation_baku_vs_monza():
    """Spec requirement: policy must change with harvest potential.

    With a half-charged battery, Baku (~7.1 MJ/lap) sustains a far more
    aggressive net spend than Monza (~3.3), so the recommended posture and its
    per-lap energy plan differ between circuits.
    """
    mpc = Tier2MPC(_frontier())
    baku = mpc.recommend(
        _state(own_est_soc_mj=1.0, circuit_harvest_potential_mj=7.1)
    )
    monza = mpc.recommend(
        _state(own_est_soc_mj=1.0, circuit_harvest_potential_mj=3.3)
    )
    assert baku.posture != monza.posture
    assert baku.per_lap_net_mj[0] > monza.per_lap_net_mj[0]


def test_low_soc_does_not_attack_and_rebuilds_reserve():
    """A near-empty battery must not be attacked; the optimiser protects SoC."""
    mpc = Tier2MPC(_frontier())
    dec = mpc.recommend(
        _state(own_est_soc_mj=0.5, circuit_harvest_potential_mj=3.3,
               gap_ahead_s=10.0, gap_behind_s=10.0)
    )
    assert dec.posture != "ATTACK"
    assert dec.min_soc_mj >= 2.0  # rebuilds to a healthy buffer
    # It protects the battery at least as well as an ATTACK would.
    assert dec.alternatives[dec.posture] >= dec.alternatives["ATTACK"]


def test_trap_blocks_attack():
    """A counter-harvest trap ahead must not be attacked."""
    mpc = Tier2MPC(_frontier())
    dec = mpc.recommend(
        _state(circuit_harvest_potential_mj=5.0, gap_ahead_s=0.8,
               belief_ahead=_belief(trap=True, p_lh=0.7, p_ot=0.8))
    )
    assert dec.posture != "ATTACK"
    assert "trap" in dec.rationale.lower()


def test_attack_when_rival_empty_and_no_trap():
    """A genuinely empty rival (Lderate) with no trap keeps us offensive.

    ATTACK and NEUTRAL both complete the pass; the optimiser stays offensive
    (never HARVEST/DEFEND) and values ATTACK at least as highly as HARVEST.
    """
    mpc = Tier2MPC(_frontier())
    dec = mpc.recommend(
        _state(circuit_harvest_potential_mj=7.1, gap_ahead_s=1.0,
               belief_ahead=_belief(p_ld=0.7, p_ot=0.1))
    )
    assert dec.posture in ("ATTACK", "NEUTRAL")
    assert dec.alternatives["ATTACK"] >= dec.alternatives["HARVEST"]


def test_horizon_scoring_changes_with_laps():
    mpc = Tier2MPC(_frontier())
    short = mpc.recommend(_state(circuit_harvest_potential_mj=4.0), horizon=4)
    long = mpc.recommend(_state(circuit_harvest_potential_mj=4.0), horizon=12)
    assert short.horizon_laps == 4
    assert long.horizon_laps == 12
    assert len(long.per_lap_net_mj) == 12


def test_needs_nonempty_frontier():
    with pytest.raises(ValueError):
        Tier2MPC(ParetoFrontier(np.zeros(0), np.zeros(0)))


# --------------------------------------------------------------------------
# Public rollout API + counterfactual projection outputs (What-If support)
# --------------------------------------------------------------------------
def test_simulate_posture_exposes_final_state():
    mpc = Tier2MPC(_frontier())
    res = mpc.simulate_posture("NEUTRAL", _state(gap_behind_s=None), horizon=8)
    for key in ("final_soc", "final_gap_ahead", "final_gap_behind"):
        assert key in res
    assert res["final_gap_behind"] is None


def test_no_rival_behind_skips_behind_dynamics():
    mpc = Tier2MPC(_frontier())
    res = mpc.simulate_posture("ATTACK", _state(gap_behind_s=None), horizon=8)
    assert res["repasses_behind"] == 0
    assert res["time_lost_behind"] == 0.0
    assert res["final_gap_behind"] is None


def test_final_state_moves_with_posture():
    mpc = Tier2MPC(_frontier())
    st = _state(gap_ahead_s=0.6, own_est_soc_mj=4.0, circuit_harvest_potential_mj=7.0)
    atk = mpc.simulate_posture("ATTACK", st, horizon=10)
    hrv = mpc.simulate_posture("HARVEST", st, horizon=10)
    assert atk["final_gap_ahead"] < hrv["final_gap_ahead"]
    assert atk["final_soc"] < hrv["final_soc"]


def test_simulate_posture_rejects_unknown_posture():
    mpc = Tier2MPC(_frontier())
    with pytest.raises(ValueError):
        mpc.simulate_posture("HOLD", _state())
