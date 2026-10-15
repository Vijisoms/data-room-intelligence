import asyncio
import json
from pathlib import Path

import pytest

from data_room_intelligence.ontology.pipeline import publish
from data_room_intelligence.ontology.reviews import record_issue_decision
from data_room_intelligence.ontology.runner import BuildRequest, ReviewResponse, run_ontology_workflow
from data_room_intelligence.ontology.store import Snapshot

ROOT = Path(__file__).parents[1]
ROOM_ID = "lone-star-basin"


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory: pytest.TempPathFactory):
    patch = pytest.MonkeyPatch()
    patch.setenv("DRI_DATA_ROOT", str(tmp_path_factory.mktemp("dri")))
    patch.setenv("DRI_OFFLINE", "1")
    result = asyncio.run(run_ontology_workflow(BuildRequest(ROOM_ID, str(ROOT / "data" / "sample-room")), {}, ReviewResponse("hold")))
    yield result, Snapshot(ROOM_ID)
    patch.undo()


def test_workflow_pauses_for_review_and_holds(snapshot) -> None:
    result, snap = snapshot
    assert result.status == "in_review"
    assert result.counts["open_blocking"] == 317 + 1350 + 640
    assert snap.meta["status"] == "in_review"


def test_gold_counts(snapshot) -> None:
    counts = snapshot[1].meta["counts"]
    assert counts["entities"] == 1596
    assert counts["entities_by_type"]["Well"] == 320
    assert counts["entities_by_type"]["EconomicLocation"] == 640
    assert counts["entities_by_type"]["LeaseholdTract"] == 360
    assert counts["entities_by_type"]["DocumentClaim"] == 18
    assert counts["relationships"] == 4928
    assert counts["relationships_by_kind"]["CROSSES_TRACT"] == 790
    assert counts["relationships_by_kind"]["TARGETS_ZONE"] == 578
    assert counts["geometries"] == 770
    assert counts["facts"] == 38463
    assert counts["issues_by_rule"] == {
        "CLAIM_MISMATCH": 2,
        "CROSSWALK_MISSING": 92,
        "FORMULA_CACHE_MISSING": 38,
        "OPERATOR_ALIAS_CONFLICT": 483,
        "OWNERSHIP_VALUE_CONFLICT": 1350,
        "UNIT_ASSIGNMENT_CONFLICT": 317,
        "VALUE_FIELD_CONFLICT": 640,
        "ZONE_ALIAS_MISSING": 62,
    }


def test_wolfcamp_a_answer_from_facts(snapshot) -> None:
    snap = snapshot[1]
    acres = snap.sql("select sum(value) from facts where measure = 'net_acres' and zone = 'WCA'")[0][0]
    locations = snap.sql(
        "select sum(l.value * w.value) from facts l join facts w using (subject, zone) "
        "where zone = 'WCA' and l.measure = 'gross_locations_10k' and w.measure = 'operational_wi'"
    )[0][0]
    assert round(acres, 2) == 38663.82
    assert round(locations, 2) == 96.98


def test_well_keeps_both_unit_links_and_conflict(snapshot) -> None:
    snap = snapshot[1]
    well = "well:42901144110000"
    location = next(e["source"] for e in snap.inn[well] if e["kind"] == "IS_WELL")
    assigned = next(e["target"] for e in snap.out[location] if e["kind"] == "ASSIGNED_TO_UNIT")
    spatial = next(e["target"] for e in snap.out[well] if e["kind"] == "LATERAL_IN_UNIT")
    assert (assigned, spatial) == ("unit:badger-draw", "unit:golden-crossing-west")
    issue = next(i for i in snap.issues_by_subject[well] if i["rule"] == "UNIT_ASSIGNMENT_CONFLICT")
    assert issue["issue_id"] == f"issue:unit-assignment-conflict:{well}"
    assert {a["locator"] for a in issue["assertions"]} >= {"ONELINE!IO2"}


def test_claim_checks(snapshot) -> None:
    claims = {n["props"]["label"]: n["props"] for n in snapshot[1].nodes.values() if n["type"] == "DocumentClaim"}
    assert claims["Avg Working Interest"]["check"] == "mismatch"
    assert claims["Total Econ Locations"]["check"] == "match"
    assert claims["Primary-Bench Net Acres"]["check"] == "match"
    assert claims["PV-10 ($MM)"]["check"] == "unverifiable"


def test_rebuild_is_identical(snapshot, tmp_path: Path) -> None:
    snap = snapshot[1]
    before = {name: (snap.gold_dir / f"{name}.parquet").read_bytes() for name in ("nodes", "edges", "facts", "issues")}
    result = asyncio.run(run_ontology_workflow(BuildRequest(ROOM_ID, str(ROOT / "data" / "sample-room")), {}, ReviewResponse("hold")))
    assert result.snapshot_id == snap.snapshot_id
    for name, content in before.items():
        assert (snap.gold_dir / f"{name}.parquet").read_bytes() == content, name


def test_publish_gate_and_decisions(snapshot) -> None:
    snap = snapshot[1]
    blocked = publish(ROOM_ID)
    assert blocked["published"] is False and blocked["open_blocking"] == 2307
    for rule in ("UNIT_ASSIGNMENT_CONFLICT", "OWNERSHIP_VALUE_CONFLICT", "VALUE_FIELD_CONFLICT"):
        record_issue_decision(ROOM_ID, f"rule:{rule}", rule, "defer to XOM", "pending XOM review", "tester", snap.snapshot_id, scope="rule")
    with pytest.raises(ValueError):
        record_issue_decision(ROOM_ID, "x", "VALUE_FIELD_CONFLICT", "KY", " ", "tester", snap.snapshot_id)
    outcome = publish(ROOM_ID)
    assert outcome["published"] is True
    meta = json.loads((snap.gold_dir / "snapshot.json").read_text())
    assert meta["status"] == "published"
