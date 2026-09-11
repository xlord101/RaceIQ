"""Phase 7 smoke tests: the Streamlit app itself (`raceiq.ui.main`).

Uses Streamlit's ``AppTest`` harness, which executes the script in-process and
surfaces any exception as `at.exception`. This is what catches the class of bug
that a plain `import` check misses - duplicate element IDs, bad widget keys,
and render-time crashes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

st = pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "src" / "raceiq" / "ui" / "main.py"


@pytest.fixture(scope="module")
def app() -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=300)
    at.run()
    return at


# --------------------------------------------------------------------------
# It renders
# --------------------------------------------------------------------------
def test_app_runs_without_exceptions(app):
    assert app.exception == [], f"app raised: {[e.value for e in app.exception]}"


def test_all_three_tabs_are_present(app):
    assert [t.label for t in app.tabs] == ["REPLAY", "SIMULATION", "EV BUS"]


def test_charts_render(app):
    # 4 (REPLAY) + 4 (SIMULATION) + 1 (EV BUS)
    assert len(app.get("plotly_chart")) == 9


def test_css_was_injected_with_every_placeholder_substituted():
    """`_CSS` is a string.Template; an unsubstituted `$x` would render literally."""
    import raceiq.ui.main as m

    assert "$" not in m._CSS
    # the base design tokens are all substituted in (HARVEST/BALANCE are only
    # used by the plotly charts, so they legitimately do not appear in CSS)
    for name in ("BG", "CARD", "BORDER", "TEXT", "MUTED", "DEPLOY"):
        assert getattr(m, name) in m._CSS, f"{name} was not substituted"


# --------------------------------------------------------------------------
# Content guarantees (spec Section 3 / 4)
# --------------------------------------------------------------------------
def test_no_emoji_in_rendered_markdown(app):
    for block in app.markdown:
        assert all(ord(ch) < 0x1F000 for ch in block.value), "no emojis in the UI"


def test_watermark_is_rendered(app):
    blob = " ".join(b.value for b in app.markdown)
    assert "Estimated" in blob


def test_timing_tower_renders_all_twenty_two_cars(app):
    from raceiq.ui.scenario import build_scenario

    blob = " ".join(b.value for b in app.markdown)
    for row in build_scenario().tower:
        assert row.driver in blob


def test_compliance_board_renders(app):
    blob = " ".join(b.value for b in app.markdown)
    assert "PASS" in blob


# --------------------------------------------------------------------------
# The headline demo is visible: trap flips GO -> HOLD
# --------------------------------------------------------------------------
def test_decision_card_shows_go_for_clean_rival(app):
    blob = " ".join(b.value for b in app.markdown)
    assert "GO" in blob


def test_trap_variant_renders_a_hold():
    """Re-run the app with the trap armed and confirm HOLD reaches the screen."""
    at = AppTest.from_file(str(APP), default_timeout=300)
    at.run()
    assert at.exception == []
    at.checkbox(key="trap").check().run()
    assert at.exception == [], f"app raised: {[e.value for e in at.exception]}"
    blob = " ".join(b.value for b in at.markdown)
    assert "HOLD" in blob
    assert "COUNTER-HARVEST TRAP" in blob.upper()


def test_ev_bus_tab_renders_a_posture(app):
    blob = " ".join(b.value for b in app.markdown)
    for posture in ("ATTACK", "NEUTRAL", "HARVEST", "DEFEND"):
        if posture in blob:
            return
    pytest.fail("EV BUS tab rendered no recognised drive posture")
