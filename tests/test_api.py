import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from data_room_intelligence.ontology.runner import BuildRequest, ReviewResponse, run_ontology_workflow

ROOT = Path(__file__).parents[1]
ROOM = ROOT / "data" / "sample-room"
SCENARIO = ROOT / "data" / "scenarios" / "new-dataset" / "Seller Well Production_2026.07.xlsx"


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory):
    patch = pytest.MonkeyPatch()
    patch.setenv("DRI_DATA_ROOT", str(tmp_path_factory.mktemp("dri")))
    patch.setenv("DRI_OFFLINE", "1")
    asyncio.run(run_ontology_workflow(BuildRequest("lone-star-basin", str(ROOM)), {}, ReviewResponse("hold")))
    from data_room_intelligence.service import api

    patch.setattr(api, "ROOM_DIR", ROOM)
    api.state.reload()
    yield TestClient(api.app)
    patch.undo()


def test_room_and_schema(client: TestClient) -> None:
    room = client.get("/api/room").json()
    assert room["counts"]["entities"] == 1596 and room["status"] == "in_review"
    schema = client.get("/api/graph/viz/schema").json()
    assert {t["type"] for t in schema["types"]} >= {"Unit", "Well", "EconomicLocation"}
    assert any(link["kind"] == "PRICED_AT" and link["count"] == 0 for link in schema["links"])


def test_search_and_neighborhood(client: TestClient) -> None:
    hits = client.get("/api/graph/viz/search", params={"q": "42901144110000"}).json()
    assert hits[0]["id"] == "well:42901144110000"
    hood = client.get("/api/graph/viz/neighborhood", params={"id": "well:42901144110000", "depth": 2}).json()
    kinds = {e["kind"] for e in hood["edges"]}
    assert {"IS_WELL", "LATERAL_IN_UNIT", "ASSIGNED_TO_UNIT", "CROSSES_TRACT"} <= kinds
    assert sum(e["conflict"] for e in hood["edges"]) >= 2
    hub = client.get("/api/graph/viz/neighborhood", params={"id": "operator:lone-star-basin-operating-llc"}).json()
    assert hub["hub"] is True and hub["depth"] == 1 and hub["capped"] > 0


def test_entity_card_and_cell_lineage(client: TestClient) -> None:
    card = client.get("/api/graph/viz/interpret", params={"id": "unit:golden-crossing-west"}).json()
    assert card["fact_count"] == 150 and card["geometry"] and card["schema"]["name"] == "Unit"
    lineage = client.get("/api/files/combocurve/lineage", params={"sheet": "ONELINE", "cell": "KY2"}).json()
    assert lineage["facts"][0]["measure"] == "dcf10_ky"
    assert lineage["mapping"]["target"] == "EconomicLocation.dcf10_ky"
    assert any(issue["rule"] == "VALUE_FIELD_CONFLICT" for issue in lineage["issues"])
    from openpyxl.utils import column_index_from_string

    ky = column_index_from_string("KY")
    grid = client.get("/api/files/combocurve/grid", params={"sheet": "ONELINE", "r0": 1, "r1": 3, "c0": ky, "c1": ky}).json()
    assert grid["rows"][0][0] == "10% Discount Cash Flow (M$)"


def test_files_documents_and_layers(client: TestClient) -> None:
    files = {f["file_id"]: f for f in client.get("/api/files").json()}
    assert files["asset-overview"]["claims"] == 10 and files["combocurve"]["sheets"]
    assert client.get("/api/files/asset-overview/pages/4.png").status_code == 200
    assert client.get("/api/files/../etc/passwd/pages/1.png").status_code == 404
    layer = client.get("/api/layers/gis-leasehold").json()
    assert all(feature["properties"]["entity"] for feature in layer["features"])


def test_named_operation_endpoint_cell_value_and_claim_checks(client: TestClient) -> None:
    zone = client.post("/api/graph/operations/zone_summary", json={"zone": "WCA"}).json()
    assert zone["data"]["net_acres"] == 38663.82 and zone["citations"]
    assert client.post("/api/graph/operations/unknown", json={}).status_code == 404
    assert client.post("/api/graph/operations/zone_summary", json={"bogus": "x"}).status_code == 422
    lineage = client.get("/api/files/combocurve/lineage", params={"sheet": "ONELINE", "cell": "KY2"}).json()
    assert round(lineage["value"], 2) == 6816.98
    checks = client.get("/api/files/asset-overview").json()["claim_checks"]
    assert sum(c["check"] == "mismatch" for c in checks.values()) == 2


def test_snapshot_queries_are_thread_safe(client: TestClient) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from shapely import from_wkb

    from data_room_intelligence.service import api

    snap = api.state.snapshot
    ids = ["unit:golden-crossing-west", "unit:badger-draw", "well:42901144110000"] * 20

    def geometry_and_facts(entity: str) -> tuple[str, int]:
        wkb = snap.sql("select wkb from geometries where entity = ?", [entity])[0][0]
        return from_wkb(wkb).geom_type, len(snap.facts(entity))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(geometry_and_facts, ids))
    assert {kind for kind, _ in results} == {"Polygon", "LineString"}
    assert results[0][1] == 150


def test_room_path_resolves_from_any_working_directory(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys

    env = {**os.environ, "DATA_ROOM_PATH": "data/sample-room"}
    probe = "from data_room_intelligence.service import api; print(api.ROOM_DIR.is_dir())"
    result = subprocess.run([sys.executable, "-c", probe], cwd=tmp_path, env=env, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "True"


def test_offline_chat_routes_to_operations(client: TestClient) -> None:
    answer = client.post("/api/graph/ask", json={"question": "What are the Wolfcamp A net acres, net locations and PV-10?"}).json()
    assert answer["operations"][0]["operation"] == "zone_summary"
    assert "38,663.82" in answer["answer"] and "96.98" in answer["answer"]
    assert any("P8" in (c["locator"] or "") for c in answer["citations"])
    profile = client.post("/api/graph/ask", json={"question": "Tell me about JARDINE 4-27 A 4LS"}).json()
    assert profile["operations"][0]["operation"] == "well_profile" and "GOLDEN CROSSING WEST" in profile["answer"]


def test_review_decision_requires_reason(client: TestClient) -> None:
    issue = client.get("/api/issues", params={"rule": "VALUE_FIELD_CONFLICT", "limit": 1}).json()["items"][0]
    bad = client.post("/api/issues/decision", json={"issue_id": issue["issue_id"], "rule": issue["rule"], "choice": "KY is PV-10", "reason": ""})
    assert bad.status_code == 422
    ok = client.post("/api/issues/decision", json={"issue_id": issue["issue_id"], "rule": issue["rule"], "choice": "KY is PV-10", "reason": "seller confirmed", "reviewer": "test"})
    assert ok.status_code == 200
    updated = client.get("/api/issues", params={"subject": issue["subject"], "rule": issue["rule"]}).json()["items"][0]
    assert updated["status"] == "decided"
    assert client.post("/api/publish", json={}).json()["published"] is False


def test_new_dataset_reusability_flow(client: TestClient) -> None:
    rejected = client.post("/api/uploads", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert rejected.status_code == 400
    uploaded = client.post("/api/uploads", files={"file": (SCENARIO.name, SCENARIO.read_bytes(), "application/octet-stream")}).json()
    proposals = {p["header"]: p for p in uploaded["proposals"]}
    assert proposals["API Number"]["target"] == "Well.api_14" and proposals["API Number"]["match_rate"] == "240/252"
    assert proposals["Production Month"]["status"] == "approved"
    assert proposals["Oil Volume"]["target"] == "Well.oil_bbl" and proposals["Oil Volume"]["status"] == "proposed"
    for header in ("API Number", "Oil Volume", "Gas Volume", "Water Volume", "Days Producing"):
        proposal = proposals[header]
        assert client.post("/api/mappings/decision", json={"field_id": proposal["field_id"], "target": proposal["target"], "status": "approved", "reason": "test"}).status_code == 200
    rebuilt = client.post("/api/rebuild").json()
    assert rebuilt["counts"]["issues_by_rule"]["UNMATCHED_KEY"] == 1
    assert rebuilt["counts"]["facts"] == 38463 + 40 * 6 * 4
    card = client.get("/api/graph/viz/interpret", params={"id": "well:42901144110000"}).json()
    oil = sorted((f["period"], f["locator"]) for f in card["facts"] if f["measure"] == "oil_bbl")
    assert oil[0] == ("2026-01-01", "Monthly Production!D2")
