"""RaceIQ 2026 - Streamlit pit-wall terminal (spec Section 3).

A professional race-engineering terminal, not a flashy AI toy: minimalist,
dark, data-dense and calm. **No emojis anywhere** - status is text (`PASS` /
`FAIL`) or a coloured chip. Every energy number carries the honest watermark
that it is estimated, because no public ERS/SoC telemetry exists.

Layout (spec 3.3)
    Header: EVENT . SESSION . LAP n/N . TRACK STATUS . WEATHER  + mode toggle
    [1.1] Timing tower (22 rows) | [1.6] Track map + decision card | [1.1] Compare + compliance
    Bottom: SoC vs lap - speed trace with clipping flags - cumulative time delta
    Footer: watermark

Run with:
    streamlit run src/raceiq/ui/main.py
"""

from __future__ import annotations

from string import Template
from typing import Dict, List

import inspect

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from raceiq.transfer import BUS_POSTURES, BusState, EVBusSolver
from raceiq.ui.scenario import Scenario, build_scenario

# `st.plotly_chart(use_container_width=...)` is deprecated from Streamlit 1.50+
# and removed after 2025-12-31, replaced by `width=`. requirements pins >=1.32,
# so probe the signature once and use whichever keyword this install supports.
_CHART_USES_WIDTH = "width" in inspect.signature(st.plotly_chart).parameters


def _chart(fig: "go.Figure", key: str) -> None:
    """Render a plotly figure full-width with a unique element key."""
    if _CHART_USES_WIDTH:
        st.plotly_chart(fig, width="stretch", key=key)
    else:
        st.plotly_chart(fig, use_container_width=True, key=key)

# --------------------------------------------------------------------------
# Design system (spec 3.2)
# --------------------------------------------------------------------------
BG = "#0F1115"
CARD = "#161A22"
BORDER = "#242A34"
TEXT = "#E6E8EB"
MUTED = "#8A93A0"
HARVEST = "#2E7D5B"
BALANCE = "#B8860B"
DEPLOY = "#C0392B"

MODE_COLOUR = {"Harvest": HARVEST, "Balance": BALANCE, "Deploy": DEPLOY}
POSTURE_COLOUR = {
    "ATTACK": DEPLOY,
    "NEUTRAL": BALANCE,
    "HARVEST": HARVEST,
    "DEFEND": "#5B8DB8",
    "HOLD": MUTED,
}

WATERMARK = (
    "Estimated SoC - inferred from public telemetry + FIA rules. "
    "No public ERS/SoC telemetry exists."
)

# Built with string.Template ($placeholders) rather than %-formatting: CSS is
# full of literal `%` and `{}`, which makes both %- and .format()-style
# substitution error-prone and silently mis-ordered.
_CSS = Template(
    """
<style>
  .stApp { background: $bg; }
  body, .stApp, .stMarkdown, p, span, div { color: $text; font-family: Inter, -apple-system, Segoe UI, sans-serif; }
  .rq-card { background: $card; border: 1px solid $border; border-radius: 7px; padding: 14px 16px; margin-bottom: 10px; }
  .rq-label { font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: $muted; font-weight: 600; }
  .rq-muted { color: $muted; font-size: 11px; }
  .rq-num { font-variant-numeric: tabular-nums; }
  table.rq { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
  table.rq th { text-align: left; font-size: 9px; letter-spacing: 0.12em; text-transform: uppercase;
                color: $muted; font-weight: 600; padding: 4px 6px; border-bottom: 1px solid $border; }
  table.rq td { padding: 3px 6px; border-bottom: 1px solid $border; }
  table.rq tr.sel td { background: rgba(255,255,255,0.045); }
  .rq-dot { display:inline-block; width:3px; height:12px; margin-right:7px; border-radius:1px; vertical-align:middle; }
  .rq-chip { font-size: 9px; letter-spacing: 0.1em; font-weight: 700; text-transform: uppercase; }
  .rq-bar { display:inline-block; width: 54px; height: 5px; background: $bartrack; border-radius: 2px;
            vertical-align: middle; margin-right: 7px; overflow: hidden; }
  .rq-bar > span { display:block; height: 100%; background: $muted; }
  .rq-hero { font-size: 40px; font-weight: 800; letter-spacing: 0.06em; line-height: 1.05; margin: 6px 0 2px; }
  .rq-why { font-size: 12px; color: $muted; margin-top: 8px; }
  .rq-trap { border: 1px solid $deploy; background: rgba(192,57,43,0.09); border-radius: 6px;
             padding: 8px 10px; font-size: 11px; letter-spacing: 0.08em; font-weight: 600;
             color: $deploy; margin-top: 10px; }
  .rq-wm { color: $muted; font-size: 10.5px; letter-spacing: 0.03em; text-align: center;
           padding: 14px 0 6px; border-top: 1px solid $border; margin-top: 18px; }
  .rq-kv { display:flex; justify-content: space-between; padding: 2px 0; font-size: 12px; }
  .rq-kv span:first-child { color: $muted; }
  .rq-hdr { display:flex; gap: 18px; align-items: baseline; flex-wrap: wrap;
            border-bottom: 1px solid $border; padding-bottom: 8px; margin-bottom: 12px; }
  .rq-hdr .t { font-size: 15px; font-weight: 700; letter-spacing: 0.05em; }
</style>
"""
).substitute(
    bg=BG, text=TEXT, card=CARD, border=BORDER, muted=MUTED,
    deploy=DEPLOY, bartrack="#3A4150",
)


def _inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _bar(pct: float) -> str:
    w = max(0.0, min(100.0, float(pct)))
    return f'<span class="rq-bar"><span style="width:{w:.0f}%"></span></span>'


def _chip(text: str, colour: str) -> str:
    return f'<span class="rq-chip" style="color:{colour}">{text}</span>'


def _kv(label: str, value: str) -> str:
    return f'<div class="rq-kv"><span>{label}</span><span class="rq-num">{value}</span></div>'


# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------
def _header(scn: Scenario, mode: str) -> None:
    st.markdown(
        f"""
        <div class="rq-hdr">
          <span class="t">RACEIQ 2026</span>
          <span class="rq-muted">{scn.event.upper()} &middot; RACE</span>
          <span class="rq-muted">LAP {scn.lap}/{scn.total_laps}</span>
          <span class="rq-muted">TRACK GREEN</span>
          <span class="rq-muted">DRY 24C</span>
          <span class="rq-chip" style="color:{TEXT}">{mode}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# Left column: timing tower
# --------------------------------------------------------------------------
def _timing_tower(scn: Scenario) -> None:
    rows: List[str] = []
    for r in scn.tower:
        sel = " class='sel'" if r.driver == scn.ego else ""
        colour = MODE_COLOUR.get(r.mode, MUTED)
        rows.append(
            f"<tr{sel}>"
            f"<td class='rq-num'>{r.position}</td>"
            f"<td><span class='rq-dot' style='background:{r.colour}'></span>{r.driver}</td>"
            f"<td class='rq-num'>{r.interval_s:+.2f}</td>"
            f"<td>{_bar(r.est_soc_pct)}<span class='rq-muted'>{r.est_soc_pct:.0f}%</span></td>"
            f"<td>{_chip(r.mode.upper(), colour)}</td>"
            f"<td class='rq-num'>{r.lap_delta_s:+.2f}</td>"
            "</tr>"
        )
    st.markdown(
        "<div class='rq-card'>"
        "<div class='rq-label'>Timing tower &middot; estimated SoC</div>"
        "<table class='rq'><tr><th>POS</th><th>DRV</th><th>INT</th><th>EST SOC</th>"
        "<th>MODE</th><th>DELTA</th></tr>"
        + "".join(rows)
        + "</table></div>",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# Centre column: track map + decision card
# --------------------------------------------------------------------------
def _track_map(scn: Scenario) -> go.Figure:
    """Schematic circuit outline with detection / activation lines."""
    th = np.linspace(0, 2 * np.pi, 400)
    r = 1.0 + 0.26 * np.sin(3 * th) + 0.10 * np.cos(5 * th)
    x, y = r * np.cos(th), r * np.sin(th) * 0.62

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=y, mode="lines", line=dict(color="#3A4150", width=2),
                             hoverinfo="skip"))

    # detection / activation markers on the longest straight
    i_det, i_act = 60, 95
    fig.add_trace(go.Scatter(x=[x[i_det]], y=[y[i_det]], mode="markers+text",
                             marker=dict(size=8, color=BALANCE, symbol="line-ns",
                                         line=dict(width=3, color=BALANCE)),
                             text=["DETECTION"], textposition="top center",
                             textfont=dict(size=8, color=BALANCE), hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=[x[i_act]], y=[y[i_act]], mode="markers+text",
                             marker=dict(size=8, color=HARVEST, symbol="line-ns",
                                         line=dict(width=3, color=HARVEST)),
                             text=["ACTIVATION"], textposition="bottom center",
                             textfont=dict(size=8, color=HARVEST), hoverinfo="skip"))

    # driver dots - ego highlighted
    for r in scn.tower:
        i = int((r.position / max(len(scn.tower), 1)) * (len(x) - 1))
        is_ego = r.driver == scn.ego
        fig.add_trace(go.Scatter(
            x=[x[i]], y=[y[i]], mode="markers+text",
            marker=dict(size=11 if is_ego else 7, color=r.colour,
                        line=dict(width=2 if is_ego else 0,
                                  color=TEXT if is_ego else "rgba(0,0,0,0)")),
            text=[r.driver] if is_ego else None,
            textposition="top center", textfont=dict(size=9, color=TEXT),
            hovertext=f"{r.driver} - P{r.position} - est SoC {r.est_soc_pct:.0f}%",
            hoverinfo="text", name=r.driver,
        ))

    fig.update_layout(
        template="plotly_dark", paper_bgcolor=CARD, plot_bgcolor=CARD,
        height=272, margin=dict(l=6, r=6, t=6, b=6), showlegend=False,
        xaxis=dict(visible=False, scaleanchor="y"), yaxis=dict(visible=False),
    )
    return fig


def _decision_card(scn: Scenario) -> None:
    d = scn.decision
    rec = d.recommendation
    colour = POSTURE_COLOUR.get(rec, TEXT)
    status = "ELIGIBLE" if d.eligible else "NOT ELIGIBLE"
    status_c = HARVEST if d.eligible else MUTED
    compliance = "OK" if scn.compliance.passed else "FAIL"
    compliance_c = HARVEST if scn.compliance.passed else DEPLOY

    st.markdown(
        "<div class='rq-card'>"
        "<div class='rq-label'>Overtake decision &middot; detection line</div>"
        f"<div class='rq-muted' style='margin-top:6px'>"
        f"GAP AT DETECTION: <b class='rq-num'>{d.gap_s:.2f} s</b> &middot; "
        f"<span style='color:{status_c}'>{status}</span> &middot; Detection gap {scn.detection_gap_s:.1f} s"
        f"</div>"
        f"<div class='rq-hero' style='color:{colour}'>{rec}</div>"
        f"<div class='rq-muted'>vs {scn.rival} &middot; posture "
        f"{_chip(scn.posture.posture, POSTURE_COLOUR.get(scn.posture.posture, TEXT))}</div>"
        "<div style='margin-top:12px'>"
        + _kv("P(pass)", f"{d.p_pass * 100:.0f}%")
        + _kv("Points gain", f"{d.points_gain:.1f}")
        + _kv("Repayment cost", f"{d.repayment_cost_s:.1f} s")
        + _kv("Repass risk", f"{d.repass_risk * 100:.0f}%")
        + _kv("EV", f"{d.ev:+.2f}")
        + _kv("Compliance", f"<span style='color:{compliance_c}'>{compliance}</span>")
        + "</div>"
        f"<div class='rq-why'>{d.why}</div>"
        + (
            f"<div class='rq-trap'>COUNTER-HARVEST TRAP - rival conserving in aero zone; "
            f"recommendation forced to HOLD</div>"
            if d.trap_flag else ""
        )
        + "</div>",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# Right column: compare + compliance
# --------------------------------------------------------------------------
def _driver_compare(scn: Scenario) -> None:
    a, b = scn.ego_row, scn.rival_row
    st.markdown(
        "<div class='rq-card'>"
        "<div class='rq-label'>Driver comparison</div>"
        + _kv(a.driver, f"{a.est_soc_pct:.0f}% est &middot; {_chip(a.mode.upper(), MODE_COLOUR.get(a.mode, MUTED))}")
        + _kv(b.driver, f"{b.est_soc_pct:.0f}% est &middot; {_chip(b.mode.upper(), MODE_COLOUR.get(b.mode, MUTED))}")
        + _kv("Delta SoC", f"{(a.est_soc_mj - b.est_soc_mj):+.2f} MJ")
        + _kv("Gap", f"{scn.gap_at_detection_s:.2f} s")
        + _kv("Rival P(empty)", f"{scn.belief.p_Lderate * 100:.0f}%")
        + _kv("Rival P(harvest)", f"{scn.belief.p_Lharvest * 100:.0f}%")
        + "</div>",
        unsafe_allow_html=True,
    )


def _compliance_board(scn: Scenario) -> None:
    rows = "".join(
        f"<tr><td>{r['rule']}</td>"
        f"<td style='text-align:right'>"
        f"<span class='rq-chip' style='color:{HARVEST if r['status'] == 'PASS' else DEPLOY}'>"
        f"{r['status']}</span></td></tr>"
        for r in scn.compliance_rows
    )
    st.markdown(
        "<div class='rq-card'>"
        "<div class='rq-label'>Compliance board</div>"
        f"<table class='rq'>{rows}</table></div>",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------
# Bottom charts
# --------------------------------------------------------------------------
def _chart_soc(scn: Scenario) -> go.Figure:
    df = scn.soc_history
    fig = go.Figure()
    for d in [c for c in df.columns if c != "lap"]:
        colour = next((r.colour for r in scn.tower if r.driver == d), MUTED)
        fig.add_trace(go.Scatter(x=df["lap"], y=df[d], mode="lines", name=d,
                                 line=dict(width=1.4, color=colour)))
    fig.update_layout(
        template="plotly_dark", paper_bgcolor=CARD, plot_bgcolor=CARD, height=210,
        margin=dict(l=34, r=8, t=26, b=26),
        title=dict(text="ESTIMATED SOC VS LAP (TOP 5)", font=dict(size=9, color=MUTED)),
        xaxis_title="lap", yaxis_title="est SoC (MJ)",
        font=dict(size=10), legend=dict(font=dict(size=9), orientation="h", y=1.12),
    )
    return fig


def _chart_speed(scn: Scenario) -> go.Figure:
    df = scn.speed_trace
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["Distance"], y=df["Speed"], mode="lines",
                             line=dict(width=1.3, color="#64C4FF"), name="Speed"))
    clipped = df[df["clipping"]]
    for x in clipped["Distance"]:
        fig.add_vline(x=float(x), line_width=1, line_dash="dot", line_color=DEPLOY,
                      opacity=0.5)
    if len(clipped):
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines",
                                 line=dict(color=DEPLOY, dash="dot"), name="CLIPPING"))
    fig.update_layout(
        template="plotly_dark", paper_bgcolor=CARD, plot_bgcolor=CARD, height=210,
        margin=dict(l=34, r=8, t=26, b=26),
        title=dict(text="SPEED TRACE WITH CLIPPING FLAGS", font=dict(size=9, color=MUTED)),
        xaxis_title="distance (m)", yaxis_title="km/h", font=dict(size=10),
        legend=dict(font=dict(size=9), orientation="h", y=1.12),
    )
    return fig


def _chart_delta(scn: Scenario, baseline: str = "RaceIQ") -> go.Figure:
    """Cumulative time delta vs the RaceIQ line (0 by construction)."""
    res = scn.comparison.results
    if baseline not in res:
        baseline = scn.comparison.best_strategy
    base = np.cumsum(np.asarray(res[baseline].lap_time_s, dtype=float))
    fig = go.Figure()
    colours = {"RaceIQ": HARVEST, "Greedy": DEPLOY, "Conservative": BALANCE}
    for name, r in res.items():
        cum = np.cumsum(np.asarray(r.lap_time_s, dtype=float))
        n = min(len(cum), len(base))
        delta = cum[:n] - base[:n]
        fig.add_trace(go.Scatter(x=np.arange(1, n + 1), y=delta, mode="lines",
                                 name=name, line=dict(width=1.6,
                                                      color=colours.get(name, MUTED))))
    fig.update_layout(
        template="plotly_dark", paper_bgcolor=CARD, plot_bgcolor=CARD, height=210,
        margin=dict(l=34, r=8, t=26, b=26),
        title=dict(text=f"CUMULATIVE TIME DELTA VS {baseline.upper()} (LOWER IS FASTER)",
                   font=dict(size=9, color=MUTED)),
        xaxis_title="lap", yaxis_title="delta (s)", font=dict(size=10),
        legend=dict(font=dict(size=9), orientation="h", y=1.12),
    )
    return fig


# --------------------------------------------------------------------------
# Tabs
# --------------------------------------------------------------------------
def _tab_replay(scn: Scenario, key_prefix: str = "replay") -> None:
    # `key_prefix` namespaces every element ID. Streamlit auto-derives element IDs
    # from type + params, so rendering this panel twice (REPLAY tab and, with a
    # different scenario, the SIMULATION tab) would otherwise raise
    # StreamlitDuplicateElementId.
    left, centre, right = st.columns([1.1, 1.6, 1.1])
    with left:
        _timing_tower(scn)
    with centre:
        st.markdown("<div class='rq-card'>", unsafe_allow_html=True)
        _chart(_track_map(scn), f"{key_prefix}_map")
        st.markdown("</div>", unsafe_allow_html=True)
        _decision_card(scn)
    with right:
        _driver_compare(scn)
        _compliance_board(scn)

    c1, c2, c3 = st.columns(3)
    with c1:
        _chart(_chart_soc(scn), f"{key_prefix}_soc")
    with c2:
        _chart(_chart_speed(scn), f"{key_prefix}_speed")
    with c3:
        _chart(_chart_delta(scn), f"{key_prefix}_delta")


def _tab_simulation() -> None:
    st.markdown(
        "<div class='rq-card'><div class='rq-label'>Simulation - synthetic what-if</div>"
        "<div class='rq-muted' style='margin-top:6px'>"
        "Everything below is computed by RaceIQ on a synthetic field. No scraped data, "
        "no ground-truth SoC - all energy values are estimates.</div></div>",
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns(3)
    with col1:
        harvest = st.slider("Circuit harvest potential (MJ/lap)", 1.0, 8.0, 2.9, 0.1)
    with col2:
        ego_index = st.slider("Ego running position", 2, 22, 3)
    with col3:
        trap = st.checkbox("Rival running counter-harvest trap", value=False)

    scn = build_scenario(harvest_mj=harvest, ego_index=ego_index - 1, trap=trap)
    _tab_replay(scn, key_prefix="sim")


def _tab_ev_bus() -> None:
    st.markdown(
        "<div class='rq-card'><div class='rq-label'>EV bus transfer &middot; PM e-Bus Sewa</div>"
        "<div class='rq-muted' style='margin-top:6px'>"
        "Same solver, different config: the 4 MJ window becomes the battery usable "
        "window plus a mandated reserve; braking zones become bus stops; Overtake Mode "
        "becomes a time-critical schedule recovery.</div></div>",
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        soc = st.slider("State of charge (%)", 5, 100, 70)
    with c2:
        stops = st.slider("Stops remaining", 1, 20, 10)
    with c3:
        slack = st.slider("Schedule slack (s)", -120, 180, 0)
    with c4:
        payload = st.slider("Payload (t)", 0.0, 6.0, 2.0)

    solver = EVBusSolver()
    state = BusState(
        soc_pct=float(soc), stops_remaining=int(stops),
        distance_to_next_stop_m=800.0, schedule_slack_s=float(slack),
        payload_tonnes=float(payload), total_stops=20,
    )
    rec = solver.recommend(state)

    colour = POSTURE_COLOUR.get(rec.mode, TEXT)
    st.markdown(
        "<div class='rq-card'>"
        f"<div class='rq-hero' style='color:{colour}'>{rec.mode_label.upper()}</div>"
        f"<div class='rq-muted'>drive mode {rec.mode} &middot; "
        f"{'feasible' if rec.feasible else 'reserve at risk'}</div>"
        "<div style='margin-top:12px'>"
        + _kv("Projected depot SoC", f"{rec.projected_soc_pct:.0f}%")
        + _kv("Reserve SoC", f"{rec.reserve_soc_pct:.0f}%")
        + _kv("Power fraction", f"{rec.power_fraction * 100:.0f}%")
        + _kv("Energy saved vs always-attack", f"{rec.energy_saved_kwh:.2f} kWh")
        + _kv("Schedule delta", f"{rec.schedule_delta_s:+.0f} s")
        + "</div>"
        f"<div class='rq-why'>{rec.rationale}</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    # mode comparison across the remaining route
    modes = list(BUS_POSTURES)
    proj = [solver.project_soc(state, m) for m in modes]
    fig = go.Figure(go.Bar(x=modes, y=proj,
                           marker_color=[POSTURE_COLOUR.get(m, MUTED) for m in modes]))
    fig.add_hline(y=rec.reserve_soc_pct, line_dash="dot", line_color=DEPLOY,
                  annotation_text="reserve", annotation_font_size=9)
    fig.update_layout(
        template="plotly_dark", paper_bgcolor=CARD, plot_bgcolor=CARD, height=230,
        margin=dict(l=34, r=8, t=26, b=26),
        title=dict(text="PROJECTED DEPOT SOC BY DRIVE MODE (%)",
                   font=dict(size=9, color=MUTED)),
        yaxis_title="SoC %", font=dict(size=10),
    )
    _chart(fig, "bus_projection")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(layout="wide", page_title="RaceIQ 2026",
                       initial_sidebar_state="collapsed")
    _inject_css()

    with st.sidebar:
        st.markdown("<div class='rq-label'>RaceIQ 2026</div>", unsafe_allow_html=True)
        event = st.selectbox("Event", ["Melbourne", "Bahrain", "Shanghai", "Monza", "Baku"], 0)
        lap = st.slider("Lap", 1, 58, 34)
        total_laps = st.number_input("Total laps", 10, 78, 58)
        ego_index = st.slider("Ego position", 2, 22, 3, key="ego")
        trap = st.checkbox("Counter-harvest trap", value=False, key="trap")

    scn = build_scenario(event=event, lap=int(lap), total_laps=int(total_laps),
                         ego_index=int(ego_index) - 1, trap=trap)

    _header(scn, "REPLAY")
    tab_replay, tab_sim, tab_bus = st.tabs(["REPLAY", "SIMULATION", "EV BUS"])
    with tab_replay:
        _tab_replay(scn)
    with tab_sim:
        _tab_simulation()
    with tab_bus:
        _tab_ev_bus()

    st.markdown(f"<div class='rq-wm'>{WATERMARK}</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
