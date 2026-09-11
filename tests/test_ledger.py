"""Phase 3 tests: the FIA compliance ledger.

An illegal plan must be rejected outright - not merely scored worse - because
the Overtake EV engine treats it as minus infinity.
"""

from __future__ import annotations

import numpy as np
import pytest

from raceiq.config import power_to_propel_kw
from raceiq.rules import RULE_LABELS, ComplianceLedger, certificate_text
from raceiq.rules.ledger import ComplianceLedger as Ledger
from raceiq.types import ComplianceResult, DeploymentPlan, PlanSegment, Segment

from conftest import needs_cache


def _seg(i: int, kind: str = "straight", speed: float = 250.0) -> Segment:
    return Segment(
        index=i, start_m=i * 10.0, end_m=(i + 1) * 10.0, kind=kind,
        mean_speed_kph=speed, entry_speed_kph=speed, exit_speed_kph=speed,
    )


def _plan(deploy_mj: float, harvest_mj: float, peak_kw: float,
          n: int = 10, overtake_mode: bool = False, **meta) -> DeploymentPlan:
    segs = []
    per_d = deploy_mj / max(n // 2, 1)
    per_h = harvest_mj / max(n - n // 2, 1)
    # Durations are long enough that the plan's power steps respect the 100 kW/s
    # slew limit; the energy/peak checks below are what these tests target.
    dur = 3.0
    for i in range(n):
        if i < n // 2:
            segs.append(PlanSegment(i, peak_kw if i == 0 else peak_kw * 0.5,
                                    per_d, 0.0, 250.0, dur))
        else:
            segs.append(PlanSegment(i, -50.0, 0.0, per_h, 250.0, dur))
    return DeploymentPlan(segments=segs, lap=5, overtake_mode=overtake_mode,
                          metadata=meta)


def test_legal_plan_passes(rules):
    led = ComplianceLedger(rules)
    res = led.check(_plan(2.0, 1.0, 300.0), speed_kph=250.0, lap=5)
    assert isinstance(res, ComplianceResult)
    assert res.passed, res.violations
    assert res.violations == []


def test_soc_window_violation(rules):
    led = ComplianceLedger(rules)
    res = led.check(_plan(6.0, 0.0, 300.0), speed_kph=250.0, lap=5)
    assert not res.passed
    assert "soc_window" in res.violations


def test_harvest_cap_violation(rules):
    led = ComplianceLedger(rules)
    res = led.check(_plan(1.0, rules.harvest_cap_mj_per_lap + 1.0, 300.0),
                    speed_kph=250.0, lap=5)
    assert not res.passed
    assert "harvest_cap" in res.violations


def test_deploy_cap_violation(rules):
    led = ComplianceLedger(rules, event_deploy_mj=2.0)
    res = led.check(_plan(4.0, 0.0, 300.0), speed_kph=250.0, lap=5)
    assert not res.passed
    assert "deploy_cap" in res.violations


def test_overtake_mode_grants_bonus_energy(rules):
    """Overtake Mode adds +0.5 MJ to the deployment allowance."""
    base = rules.deploy_mj_per_lap
    led = ComplianceLedger(rules, event_deploy_mj=base)
    spend = base + 0.3                       # over without the bonus
    assert not led.check(_plan(spend, 0.0, 300.0), lap=5).passed
    with_mode = led.check(_plan(spend, 0.0, 300.0, overtake_mode=True), lap=5)
    assert "deploy_cap" not in with_mode.violations


def test_power_to_propel_violation_at_speed(rules):
    led = ComplianceLedger(rules)
    v = 330.0
    cap = power_to_propel_kw(v, rules)       # 200 kW
    assert led.check(_plan(2.0, 1.0, cap - 10), speed_kph=v, lap=5).passed is not None
    res = led.check(_plan(2.0, 1.0, cap + 50), speed_kph=v, lap=5)
    assert not res.passed
    assert "power_to_propel" in res.violations


def test_boost_cap_violation(rules):
    led = ComplianceLedger(rules)
    boost_cap = rules.base_deploy_kw + rules.race_boost_cap_kw
    res = led.check(_plan(2.0, 1.0, boost_cap + 10), speed_kph=100.0, lap=5)
    assert not res.passed
    assert "boost_cap" in res.violations


def test_start_speed_rule_only_applies_on_lap_one(rules):
    led = ComplianceLedger(rules)
    slow = _plan(2.0, 1.0, 200.0)
    res_l1 = led.check(slow, speed_kph=10.0, lap=1)
    assert "start_min_speed" in res_l1.violations
    res_l5 = led.check(slow, speed_kph=10.0, lap=5)
    assert "start_min_speed" not in res_l5.checks


def test_pit_gain_and_torque_violations(rules):
    led = ComplianceLedger(rules)
    res = led.check(_plan(2.0, 1.0, 300.0,
                          pit_stationary_gain_kj=rules.pit_stationary_gain_kj + 1,
                          mgu_k_torque_nm=rules.mgu_k_torque_nm + 1), lap=5)
    assert "pit_gain" in res.violations
    assert "torque" in res.violations


def test_slew_rate_violation(rules):
    led = ComplianceLedger(rules)
    segs = [
        PlanSegment(0, 0.0, 0.0, 0.0, 250.0, 0.2),
        PlanSegment(1, 350.0, 0.07, 0.0, 250.0, 0.2),   # 1750 kW/s
    ]
    res = led.check(DeploymentPlan(segments=segs, lap=5), speed_kph=250.0, lap=5)
    assert "slew_rate" in res.violations


def test_check_power_profile_matches_manual_plan(rules):
    led = ComplianceLedger(rules)
    segs = [_seg(i) for i in range(6)]
    powers = [200.0, 200.0, 250.0, -50.0, -50.0, 0.0]
    res = led.check_power_profile(powers, segs, lap=5)
    assert isinstance(res, ComplianceResult)
    assert set(res.checks) >= {"soc_window", "harvest_cap", "deploy_cap"}


def test_board_rows_and_certificate_are_text_only(rules):
    led = ComplianceLedger(rules)
    res = led.check(_plan(2.0, 1.0, 300.0), speed_kph=250.0, lap=5)
    rows = led.board_rows(res)
    assert rows and all(set(r) == {"rule", "status", "detail"} for r in rows)
    assert all(r["status"] in ("PASS", "FAIL") for r in rows)
    cert = certificate_text(res)
    assert "OVERALL" in cert
    assert "PASS" in cert
    # no emojis anywhere in the compliance output
    for s in [cert] + [r["rule"] + r["detail"] for r in rows]:
        assert all(ord(ch) < 0x2190 for ch in s), s


def test_rule_labels_cover_every_check(rules):
    led = ComplianceLedger(rules)
    res = led.check(_plan(2.0, 1.0, 300.0), speed_kph=250.0, lap=5)
    for k in res.checks:
        assert k in RULE_LABELS, k


def test_every_rule_can_fail(rules):
    """Each rule must be reachable - a rule that can never fail is dead code."""
    led = ComplianceLedger(rules)
    seen = set()
    cases = [
        _plan(9.0, 0.0, 300.0),                                   # soc_window
        _plan(1.0, 50.0, 300.0),                                  # harvest_cap
        _plan(99.0, 0.0, 300.0),                                  # deploy_cap
        _plan(2.0, 1.0, 400.0, pit_stationary_gain_kj=1e6,
              mgu_k_torque_nm=1e6),                                # pit/torque/boost
    ]
    for plan in cases:
        seen |= set(led.check(plan, speed_kph=340.0, lap=1).violations)
    assert seen >= {"soc_window", "harvest_cap", "deploy_cap",
                    "power_to_propel", "boost_cap", "pit_gain", "torque"}


@needs_cache
def test_ledger_on_dp_plan(rules, real_segments):
    """The plan Tier-1 actually proposes must clear the compliance ledger.

    The DP is solved against the same FIA stack, so its recovered plan must be
    legal. We check the planner-level rules (energy window, power-to-propel,
    zone and boost caps) per segment; the hardware slew limit is a controller
    concern, not a coarse-planner one, so it is disabled here.
    """
    if not real_segments:
        pytest.skip("no cached segments")
    from raceiq.optimize.tier1_dp import Tier1DP

    dp = Tier1DP(rules, real_segments)
    plan = dp.deployment_plan()
    speeds = [s.mean_speed_kph for s in real_segments]
    res = ComplianceLedger(rules).check(
        plan, lap=5, segment_speeds=speeds, slew_rate=False
    )
    assert "soc_window" not in res.violations
    assert "power_to_propel" not in res.violations
    assert "boost_cap" not in res.violations
    assert "zone_deploy" not in res.violations


def test_ledger_is_rejecting_not_scoring(rules):
    """An illegal plan returns passed=False; it is not given a soft penalty."""
    led = ComplianceLedger(rules)
    assert led.check(_plan(20.0, 0.0, 300.0), lap=5).passed is False
