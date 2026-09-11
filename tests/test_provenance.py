"""Phase 3 tests — the shared provenance model.

Every value in the frontend JSON contract carries a label from the closed set
``actual`` / ``inferred`` / ``counterfactual``. The rules pinned here:

* source facts (positions, order) are ``actual`` and are never overwritten;
* RaceIQ quantities (estimated SoC, ERS mode) are ``inferred``, never
  ``actual`` — no public ERS/SoC telemetry exists;
* projections (strategy comparison) are ``counterfactual`` and never
  presented as race events.
"""

from __future__ import annotations

import json

from raceiq.ui.contract import PROVENANCE, scenario_to_frontend
from raceiq.ui.scenario import build_scenario

ACTUAL, INFERRED, COUNTERFACTUAL = PROVENANCE


def _payload(**kw) -> dict:
    kw.setdefault("trap", False)
    kw.setdefault("seed", 7)
    kw.setdefault("focus_gap", 0.7)
    return scenario_to_frontend(build_scenario(**kw))


def test_taxonomy_is_closed():
    assert set(PROVENANCE) == {"actual", "inferred", "counterfactual"}


def test_frame_level_provenance_labels():
    p = _payload()
    prov = p["provenance"]
    assert prov["positions"] == ACTUAL
    assert prov["energy"] == INFERRED
    assert prov["decision"] == INFERRED
    assert prov["comparison"] == COUNTERFACTUAL


def test_tower_rows_mark_sources_and_inference():
    row = _payload()["tower"][0]
    assert row["position_provenance"] == ACTUAL
    assert row["soc_provenance"] == INFERRED
    assert row["mode_provenance"] == INFERRED


def test_ego_and_rival_rows_carry_provenance():
    p = _payload()
    for row in (p["ego_row"], p["rival_row"]):
        assert row["position_provenance"] == ACTUAL
        assert row["soc_provenance"] == INFERRED
        assert row["mode_provenance"] == INFERRED


def test_grid_position_order_matches_tower():
    """The frontend rows must never diverge from the source grid."""
    p = _payload()
    grid_pos = [r["position"] for r in p["grid"]]
    tower_pos = [r["position"] for r in p["tower"]]
    assert grid_pos == tower_pos


def test_no_drivers_are_fabricated():
    """Frontend rows are an exact projection of the source grid."""
    p = _payload()
    grid_codes = {r["code"] for r in p["grid"]}
    tower_codes = {r["driver"] for r in p["tower"]}
    assert grid_codes == tower_codes
    for r in p["grid"]:
        assert r["position_provenance"] == ACTUAL


def test_comparison_rows_are_counterfactual():
    for row in _payload()["comparison"]["rows"]:
        assert row["provenance"] == COUNTERFACTUAL


def test_contract_roundtrips_with_provenance():
    p = _payload()
    again = json.loads(json.dumps(p))
    assert again["provenance"] == p["provenance"]
    assert again["tower"][0]["soc_provenance"] == INFERRED
    assert again["comparison"]["rows"][0]["provenance"] == COUNTERFACTUAL