"""Phase 0 tests: config loading and FIA constant derivation."""

from __future__ import annotations

import pytest

from raceiq import config as cfg


def test_config_dir_exists():
    assert cfg.config_dir().is_dir()
    for name in ("rules_2026.json", "ev_bus.json", "circuits.json", "hmm_priors.json"):
        assert (cfg.config_dir() / name).is_file(), name


def test_rules_core_constants():
    r = cfg.load_rules()
    assert r.soc_window_mj == 4.0
    # FIA Art. 5.4.9 standard Recharge ceiling: 8.5 MJ/lap (Master Plan Phase 2).
    assert r.harvest_cap_mj_per_lap == 8.5
    assert r.mgu_k_max_kw == 350.0
    assert r.race_boost_cap_kw == 150.0
    assert r.mgu_k_torque_nm == 500.0
    assert r.start_min_speed_kph == 50.0
    assert r.pit_stationary_gain_kj == 100.0
    assert r.slew_rate_kw_per_s == 100.0
    assert r.detection_gap_s == 1.0
    assert r.overtake_bonus_mj == 0.5
    assert r.mguh_deleted is True
    assert r.cars == 22


def test_power_to_propel_rampdown():
    r = cfg.load_rules()
    # FIA 2026 C5.2.8 (Master Plan Phase 2): min(350, 1800-5v) below 340 km/h,
    # 6900-20v taper 340-345 km/h, zero above 345 km/h without Overtake Mode.
    assert cfg.power_to_propel_kw(0, r) == 350.0
    assert cfg.power_to_propel_kw(300, r) == pytest.approx(300.0)  # 1800-1500
    assert cfg.power_to_propel_kw(310, r) == pytest.approx(250.0)  # 1800-1550
    assert cfg.power_to_propel_kw(330, r) == pytest.approx(150.0)  # 1800-1650
    assert cfg.power_to_propel_kw(339.9, r) == pytest.approx(100.5, abs=0.2)
    assert cfg.power_to_propel_kw(340, r) == pytest.approx(100.0)  # 6900-6800
    assert cfg.power_to_propel_kw(342, r) == pytest.approx(60.0)   # 6900-6840
    assert cfg.power_to_propel_kw(344.9, r) == pytest.approx(2.0, abs=0.5)
    assert cfg.power_to_propel_kw(345, r) == pytest.approx(0.0)
    assert cfg.power_to_propel_kw(350, r) == pytest.approx(0.0)
    assert cfg.power_to_propel_kw(355, r) == pytest.approx(0.0)
    # monotone non-increasing in speed
    vals = [cfg.power_to_propel_kw(v, r) for v in range(0, 360, 5)]
    assert all(a >= b - 1e-9 for a, b in zip(vals, vals[1:]))


def test_fuel_flow_limit():
    r = cfg.load_rules()
    assert cfg.fuel_flow_limit_kg_per_h(10000, r) == pytest.approx(0.27 * 10000 + 165)
    # above the knee the limit is capped at the knee value
    knee = cfg.fuel_flow_limit_kg_per_h(10500, r)
    assert cfg.fuel_flow_limit_kg_per_h(12000, r) == pytest.approx(knee)


def test_event_configs():
    for name in cfg.list_events():
        ev = cfg.load_event(name)
        assert ev.event
        assert ev.year == 2026
        assert ev.detection_gap_s > 0
        assert ev.deploy_mj_with_overtake >= ev.deploy_mj_without_overtake


def test_shanghai_event_note():
    ev = cfg.load_event("Shanghai")
    assert ev.detection_line_m == 5130
    assert ev.activation_line_m == 5250
    assert ev.activation_line_m > ev.detection_line_m
    assert len(ev.special_power_reduction_zones) == 2


def test_bahrain_unverified_template():
    ev = cfg.load_event("Bahrain")
    # template: unconfirmed lines must be None so the UI falls back, never invents
    assert ev.verified is False
    assert ev.detection_line_m is None


def test_ev_bus_config():
    b = cfg.load_ev_bus()
    assert b.battery_usable_window_kwh == 250
    assert b.reserve_soc_pct == 15
    assert b.regen_per_stop_kwh == 0.8
    assert b.max_power_kw == 250
    assert b.stops_on_route == 20
    assert set(b.modes) == {"ATTACK", "NEUTRAL", "HARVEST", "DEFEND"}


def test_circuits_registry():
    c = cfg.load_circuits()
    for key in ("Melbourne", "Monza", "Baku"):
        assert key in c
        assert c[key].lap_length_m > 3000
        assert c[key].fastf1_event
    # the ablation pair must differ substantially in harvest potential
    monza = c["Monza"].brake_harvest_potential_mj
    baku = c["Baku"].brake_harvest_potential_mj
    assert baku > monza * 1.5
    assert c["Baku"].simulation_only is True  # not raced yet in 2026


def test_hmm_priors_shape_and_stochasticity():
    h = cfg.load_hmm_priors()
    assert len(h.states) == 8
    assert len(h.ers_states) == 4
    init = h.initial_ers
    assert sum(init.values()) == pytest.approx(1.0, abs=1e-6)
    tr = h.transitions
    for a in h.ers_states:
        assert sum(tr[a].values()) == pytest.approx(1.0, abs=1e-6)
    # asymmetry: Lharvest can recover to H/M, Lderate cannot bypass recovery
    assert tr["Lharvest"]["H"] > tr["Lderate"]["H"]
    assert tr["Lderate"]["Lharvest"] > tr["Lharvest"]["Lderate"]
    # delta_throttle separates Lharvest (trap) from Lderate (empty)
    em = h.emissions["delta_throttle"]
    assert em["Lderate"]["mean"] > em["Lharvest"]["mean"]


# --------------------------------------------------------------------------
# Recharge ceiling variants (Master Plan Phase 2: never the blanket 9 MJ)
# --------------------------------------------------------------------------


def test_recharge_standard_ceiling_is_8_5():
    """FIA Art. 5.4.9 standard race Recharge ceiling is 8.5 MJ/lap, not 9.0."""
    r = cfg.load_rules()
    assert r.recharge_standard_mj == 8.5
    assert "standard" in r.recharge_variants_mj
    assert r.recharge_variants_mj["standard"] == 8.5


def test_recharge_variant_limits():
    """Event/session-specific Recharge ceilings must come from config."""
    r = cfg.load_rules()
    assert r.recharge_limit_mj("standard") == pytest.approx(8.5)
    assert r.recharge_limit_mj("reduced_event") == pytest.approx(7.5)
    assert r.recharge_limit_mj("qualifying") == pytest.approx(7.0)
    assert r.recharge_limit_mj("safety_car") == pytest.approx(6.0)
    assert r.recharge_limit_mj("low_grip") == pytest.approx(7.0)


def test_recharge_conditional_bonus():
    """Stewards' conditional +0.5 MJ allowance is *added*, never the base."""
    r = cfg.load_rules()
    assert r.recharge_limit_mj("standard", conditional_bonus=True) == pytest.approx(9.0)
    assert r.recharge_limit_mj("reduced_event", conditional_bonus=True) == pytest.approx(8.0)
    # without the bonus the ceiling must be unchanged
    assert r.recharge_limit_mj("safety_car") == pytest.approx(6.0)


def test_recharge_unknown_regime_raises():
    """A typo regime must never silently fall back to a fake FIA limit."""
    r = cfg.load_rules()
    with pytest.raises(cfg.ConfigError):
        r.recharge_limit_mj("not_a_regime")


# --------------------------------------------------------------------------
# Melbourne / Monza event notes (honest fallback when unconfirmed)
# --------------------------------------------------------------------------


def test_melbourne_event_honest_fallback():
    ev = cfg.load_event("Melbourne")
    assert ev.event == "Melbourne"
    assert ev.year == 2026
    assert ev.verified is False
    # detection/activation not confirmable from a published 2026 event note ->
    # null (honest fallback), never invented
    assert ev.detection_line_m is None
    assert ev.activation_line_m is None
    assert ev.recharge_mj == 8.5
    assert ev.deploy_mj_without_overtake == 8.5
    assert ev.deploy_mj_with_overtake == 8.5


def test_monza_event_honest_fallback():
    ev = cfg.load_event("Monza")
    assert ev.event == "Monza"
    assert ev.year == 2026
    assert ev.verified is False
    assert ev.detection_line_m is None
    assert ev.activation_line_m is None
    assert ev.recharge_mj == 8.5
    assert ev.deploy_mj_without_overtake == 8.5
    assert ev.deploy_mj_with_overtake == 8.5


def test_missing_config_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("RACEIQ_CONFIG_DIR", str(tmp_path))
    with pytest.raises(cfg.ConfigError):
        cfg.load_rules(reload=True)
