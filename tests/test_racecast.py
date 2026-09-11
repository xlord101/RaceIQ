"""Tests for the full-race simulation frames (src/raceiq/ui/racecast.py)."""

import pytest

from raceiq.ui.racecast import build_racecast


@pytest.fixture(scope="module")
def cast():
    # short race keeps the suite fast; behaviour is lap-count independent
    return build_racecast("Melbourne", total_laps=8, seed=7)


def test_racecast_has_one_frame_per_lap(cast):
    assert len(cast.laps) == 8
    assert [f.lap for f in cast.laps] == list(range(1, 9))


def test_every_frame_has_all_22_cars(cast):
    for f in cast.laps:
        assert len(f.cars) == 22
        assert [c.position for c in f.cars] == list(range(1, 23))


def test_racecast_is_for_haas(cast):
    assert cast.our_team == "Haas F1 Team"
    for f in cast.laps:
        assert {h.code for h in f.haas} <= {"OCO", "BEA"}
        assert all(h.team == "Haas F1 Team" for h in f.haas)


def test_soc_stays_inside_the_window_and_is_not_degenerate(cast):
    """Regression: an unbalanced energy model drained every car to 0 %."""
    for f in cast.laps:
        for c in f.cars:
            assert 0.0 <= c.est_soc_pct <= 100.0
    # the field must actually spread out, not sit pinned at one value
    last = cast.laps[-1]
    socs = [c.est_soc_pct for c in last.cars]
    assert max(socs) - min(socs) > 5.0, socs


def test_positions_change_as_the_race_progresses(cast):
    """Cars must actually race - the order cannot be frozen."""
    first = {c.code: c.position for c in cast.laps[0].cars}
    last = {c.code: c.position for c in cast.laps[-1].cars}
    assert sum(1 for k in first if first[k] != last[k]) > 0


def test_haas_frames_carry_the_priced_bet(cast):
    for f in cast.laps:
        for h in f.haas:
            assert h.action in ("ATTACK", "HOLD", "HARVEST", "DEFEND")
            assert h.go in ("GO", "HOLD")
            assert 0.0 <= h.p_pass <= 1.0
            assert h.risk_pts >= 0.0
            assert h.reward_pts >= 0.0
            assert len(h.rationale) > 10


def test_risk_reward_ratio_is_consistent(cast):
    for f in cast.laps:
        for h in f.haas:
            if h.risk_pts > 1e-9:
                assert h.risk_reward is not None
                assert abs(h.risk_reward - h.reward_pts / h.risk_pts) < 1e-2
            else:
                assert h.risk_reward is None


def test_action_matches_go_flag(cast):
    for f in cast.laps:
        for h in f.haas:
            if h.go == "GO":
                assert h.action == "ATTACK"
            else:
                assert h.action == "HOLD"


def test_as_dict_is_json_serialisable(cast):
    import json

    text = json.dumps(cast.as_dict())
    assert "Haas F1 Team" in text
    assert "watermark" in json.loads(text)


def test_cars_expose_telemetry_for_the_hover_card(cast):
    f = cast.laps[2]
    for c in f.cars[:5]:
        assert 0.0 <= c.throttle <= 1.0
        assert c.speed_kph > 0.0
        assert isinstance(c.clipping, bool)
        assert c.mode  # non-empty ERS mode label
