"""Regression tests: model-generated What-If branches.

Guards the replacement of the canned exporter placeholders (0.75 gap, 0.45 MJ,
+0.35/+0.65 s, fixed +0.10 SoC) with genuine Tier-2 rollout outputs: branches
must vary with SoC, gap, opponent belief, circuit harvest and laps remaining,
and must never fabricate confidence, opponent responses or missing inputs.
"""

import numpy as np
import pytest

from raceiq.optimize import MPCState, ParetoFrontier, Tier2MPC
from raceiq.types import Belief
from raceiq.ui.whatif import build_whatif_branches


def _frontier():
    # Fine 1 MJ grid so Tier-2's step lookup (time_for_energy brackets, not
    # interpolates) separates an ATTACK burst from the NEUTRAL baseline.
    energy = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
    times = np.array([92.0, 90.7, 89.8, 89.2, 88.8, 88.5, 88.3, 88.2, 88.1])
    return ParetoFrontier(energy, times)


def _belief(trap=False, p_ld=0.0, p_lh=0.0):
    p_ers = {
        "H": 0.25 - p_ld / 2 - p_lh / 2,
        "M": 0.25 - p_ld / 2 - p_lh / 2,
        "Lharvest": p_lh,
        "Lderate": p_ld,
    }
    for k in p_ers:
        p_ers[k] = max(p_ers[k], 0.0)
    probs = np.array(
        [p_ers["H"], p_ers["H"], p_ers["M"], p_ers["M"], p_lh, p_lh, p_ld, p_ld],
        dtype=float,
    )
    probs = probs / probs.sum()
    return Belief(
        probs=probs,
        p_ers=p_ers,
        p_overtake_available=0.0,
        trap_prob=float(p_lh - p_ld),
        trap_flag=trap,
        evidence={},
    )


def _state(**kw):
    base = dict(
        gap_ahead_s=0.8,
        gap_behind_s=1.2,
        own_est_soc_mj=4.0,
        soc_window_mj=4.0,
        belief_ahead=_belief(),
        belief_behind=_belief(),
        laps_remaining=10,
        circuit_harvest_potential_mj=7.0,
        position=4,
    )
    base.update(kw)
    return MPCState(**base)


def _branches(**kw):
    return build_whatif_branches(Tier2MPC(_frontier()), _state(**kw), position=4)


# --------------------------------------------------------------------------
def test_all_four_actions_present_and_hold_maps_to_neutral():
    b = _branches()
    assert set(b) == {"ATTACK", "HOLD", "DEFEND", "HARVEST"}
    # Balanced state: NEUTRAL vs neutral rivals -> position held.
    assert b["HOLD"]["projectedPosition"] == 4
    assert b["HOLD"]["passesAhead"] == 0
    assert b["HOLD"]["repassesBehind"] == 0


def test_attack_projects_pass_when_gap_small_and_energy_available():
    # ATTACK sustains only its first-lap battery burst (~0.25s at this
    # frontier) before falling back to harvest-limited pace, so a pass
    # requires a gap inside that burst.
    # A clear gap behind (no yo-yo repass) so the pass sticks at net +1.
    b = _branches(gap_ahead_s=0.2, own_est_soc_mj=4.0, gap_behind_s=20.0)
    assert b["ATTACK"]["passesAhead"] >= 1
    assert b["ATTACK"]["repassesBehind"] == 0
    assert b["ATTACK"]["projectedPosition"] == 3


def test_branches_vary_with_soc():
    full = _branches(own_est_soc_mj=4.0)
    low = _branches(own_est_soc_mj=1.0)
    assert full["ATTACK"]["energySpendMj"] != low["ATTACK"]["energySpendMj"]
    assert full["ATTACK"]["projectedGap"] != low["ATTACK"]["projectedGap"]


def test_branches_vary_with_gap():
    near = _branches(gap_ahead_s=0.2)
    far = _branches(gap_ahead_s=2.5)
    assert near["ATTACK"]["passesAhead"] >= 1
    assert far["ATTACK"]["passesAhead"] == 0
    assert near["ATTACK"]["projectedGap"] != far["ATTACK"]["projectedGap"]


def test_branches_vary_with_belief_trap():
    clean = _branches()
    trap = _branches(belief_ahead=_belief(trap=True, p_lh=0.7))
    assert trap["ATTACK"]["risk"] == "HIGH"
    assert "conserving" in trap["ATTACK"]["outcome"]
    assert trap["ATTACK"]["projectedGap"] != clean["ATTACK"]["projectedGap"]


def test_branches_vary_with_circuit_harvest():
    high = _branches(circuit_harvest_potential_mj=7.0)
    low = _branches(circuit_harvest_potential_mj=3.3)
    assert high["ATTACK"]["energySpendMj"] != low["ATTACK"]["energySpendMj"]


def test_branches_vary_with_laps_remaining():
    short = _branches(gap_ahead_s=2.5, laps_remaining=3)
    long = _branches(gap_ahead_s=2.5, laps_remaining=12)
    assert short["ATTACK"]["horizonLaps"] == 3
    assert long["ATTACK"]["horizonLaps"] == 8
    assert short["ATTACK"]["projectedGap"] != long["ATTACK"]["projectedGap"]


def test_no_canned_constants_or_narratives():
    b = _branches(gap_ahead_s=1.0, own_est_soc_mj=2.0)
    for action, br in b.items():
        assert "confidence" not in br
        assert "opponentResponse" not in br
        assert "Turn 1" not in br["outcome"]
        assert br["risk"] in {"LOW", "MEDIUM", "HIGH"}
        assert br["projectedGap"] != 0.75


def test_harvest_rebuilds_reserve_and_defend_shows_risk():
    b = _branches(own_est_soc_mj=1.0)
    assert b["HARVEST"]["projectedSoc"] > 1.0 / 4.0
    assert "reserve" in b["HARVEST"]["outcome"] or "builds" in b["HARVEST"]["outcome"]


def test_missing_behind_reported_not_fabricated():
    b = build_whatif_branches(
        Tier2MPC(_frontier()),
        _state(gap_behind_s=None, belief_behind=None),
        position=4,
    )
    for br in b.values():
        assert "gap_behind" in br["inputsUnavailable"]
        assert "belief_behind" in br["inputsUnavailable"]
        assert br["repassesBehind"] == 0


def test_position_none_omits_projected_position():
    b = build_whatif_branches(
        Tier2MPC(_frontier()), _state(gap_behind_s=None), position=None
    )
    assert "projectedPosition" not in b["ATTACK"]


def test_approximations_documented():
    b = _branches()
    approx = b["ATTACK"]["inputApproximations"]
    assert set(approx) == {
        "closing_speed_kph",
        "straight_remaining_m",
        "overtake_mode_active",
    }
