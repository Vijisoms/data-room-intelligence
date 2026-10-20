"""Projects, the per-project model extension, concept discovery, the generic recipe, decisions in answers and snapshot diffs."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from data_room_intelligence.ontology.runner import BuildRequest, ReviewResponse, run_ontology_workflow

ROOT = Path(__file__).parents[1]
ROOM = ROOT / "data" / "sample-room"
CROSSWALK = ROOT / "data" / "scenarios" / "crosswalk" / "Battery Facility Crosswalk_2026.09.xlsx"
LEASES = ROOT / "data" / "scenarios" / "new-concept" / "Lease Schedule_2026.09.xlsx"


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory):
    patch = pytest.MonkeyPatch()
    patch.setenv("DRI_DATA_ROOT", str(tmp_path_factory.mktemp("dri")))
    patch.setenv("DRI_OFFLINE", "1")
    asyncio.run(run_ontology_workflow(BuildRequest("lone-star-basin", str(ROOM)), {}, ReviewResponse("hold")))
    from data_room_intelligence.service import api

    api.state.reload("lone-star-basin")
    yield TestClient(api.app)
    patch.undo()


def upload(client: TestClient, path: Path, room: str = "lone-star-basin") -> dict:
    response = client.post(f"/api/uploads?room={room}", files={"file": (path.name, path.read_bytes(), "application/octet-stream")})
    assert response.status_code == 200, response.text
    return response.json()


def test_projects_list_create_and_scope(client: TestClient) -> None:
    listed = client.get("/api/projects").json()
    sample = next(p for p in listed["projects"] if p["room_id"] == "lone-star-basin")
    assert sample["has_snapshot"] and sample["files"] == 10 and sample["open_issues"]["blocking"] == 2307
    assert sample["catalog_version"] == "0.1.0"
    created = client.post("/api/projects", json={"name": "Permian Deal 2", "description": "second room"}).json()
    assert created["room_id"] == "permian-deal-2" and created["has_snapshot"] is False and created["status"] == "empty"
    assert client.post("/api/projects", json={"name": "Permian Deal 2"}).status_code == 400
    assert client.get("/api/room?room=permian-deal-2").status_code == 503
    assert client.get("/api/room?room=nope").status_code == 404
    # The new project builds from its own files only: one Asset node, no issues, no decisions.
    rebuilt = client.post("/api/rebuild?room=permian-deal-2").json()
    assert rebuilt["counts"]["entities"] == 1 and rebuilt["counts"]["issues"] == 0
    assert client.get("/api/room?room=permian-deal-2").json()["name"] == "Permian Deal 2"
    assert client.get("/api/room").json()["room_id"] == "lone-star-basin"


def test_crosswalk_fills_the_priced_at_gap(client: TestClient) -> None:
    before = client.post("/api/graph/operations/gap_report", json={}).json()["data"]["pricing_crosswalk"]
    assert before["linked"] == 0
    uploaded = upload(client, CROSSWALK)
    proposals = {p["header"]: p for p in uploaded["proposals"]}
    assert proposals["Battery Code"]["target"] == "BatteryCode.code" and proposals["Battery Code"]["kind"] == "key"
    assert proposals["Sales Facility"]["target"] == "BatteryCode.PRICED_AT" and proposals["Sales Facility"]["kind"] == "link"
    assert uploaded["model_proposals"] == []  # every column fits the catalog: no model change needed
    for proposal in proposals.values():
        assert client.post("/api/mappings/decision", json={"field_id": proposal["field_id"], "target": proposal["target"], "status": "approved", "reason": "seller crosswalk"}).status_code == 200
    rebuilt = client.post("/api/rebuild").json()
    assert rebuilt["counts"]["relationships_by_kind"]["PRICED_AT"] == 92
    assert "CROSSWALK_MISSING" not in rebuilt["counts"]["issues_by_rule"]
    assert rebuilt["counts"]["issues_by_rule"]["UNMATCHED_KEY"] == 1  # BATTERY901 and BATTERY902
    after = client.post("/api/graph/operations/gap_report", json={}).json()
    assert after["data"]["pricing_crosswalk"]["linked"] == 92 and "links 92 of 92" in after["summary"]
    schema = client.get("/api/graph/viz/schema").json()
    assert next(l for l in schema["links"] if l["kind"] == "PRICED_AT")["count"] == 92
    card = client.get("/api/graph/viz/interpret", params={"id": "battery:battery10"}).json()
    link = next(l for l in card["links"] if l["kind"] == "PRICED_AT")
    assert link["other"]["type"] == "PricingFacility" and link["method"] == "crosswalk" and link["locator"] == "Crosswalk!B2"


def test_new_concept_is_proposed_approved_and_built(client: TestClient) -> None:
    uploaded = upload(client, LEASES)
    assert uploaded["proposals"] == []  # no existing key matches a lease schedule
    [proposal] = uploaded["model_proposals"]
    assert proposal["kind"] == "new_entity" and proposal["subject"] == "Lease" and proposal["status"] == "proposed"
    ops = [item["op"] for item in proposal["items"]]
    assert ops.count("add_entity_type") == 1 and ops.count("add_relationship") == 2 and ops.count("add_measure") == 3
    entity = next(i for i in proposal["items"] if i["op"] == "add_entity_type")["entity_type"]
    assert entity["key"] == "lease_no" and {p["name"] for p in entity["properties"]} >= {"lease_no", "lessor", "status", "effective_date", "expiration_date"}
    assert {r["relationship"]["target"] for r in proposal["items"] if r["op"] == "add_relationship"} == {"Unit", "County"}
    assert {m["header"] for m in proposal["mappings"]} == {"Lease No.", "Lessor", "Unit", "County", "Effective Date", "Expiration Date", "Status", "Gross Acres", "Net Acres", "Royalty (%)"}
    files = {f["path"]: f for f in client.get("/api/files").json()}
    assert files[f"incoming/{LEASES.name}"]["model_proposal"] == proposal["proposal_id"]
    # Rebuilding keeps the proposal (and later its decision) instead of re-proposing.
    assert [p["proposal_id"] for p in client.get("/api/model/proposals").json()] == [proposal["proposal_id"]]

    decided = client.post(f"/api/model/proposals/{proposal['proposal_id']}/decision", json={"status": "approved", "reviewer": "steward", "reason": "lease schedule is in scope"}).json()
    assert decided["proposal"]["status"] == "approved" and decided["proposal"]["catalog_version"] == "0.1.0+lone-star-basin.1"
    counts = decided["rebuild"]["counts"]
    assert counts["entities_by_type"]["Lease"] == 124
    assert counts["relationships_by_kind"]["LEASE_IN_UNIT"] == 122 and counts["relationships_by_kind"]["LEASE_IN_COUNTY"] == 124
    assert counts["issues_by_rule"]["UNMATCHED_LINK"] == 1  # two rows name a unit the room does not have
    room = client.get("/api/room").json()
    assert room["catalog_version"] == "0.1.0+lone-star-basin.1"
    catalog = client.get("/api/catalog").json()
    lease = next(t for t in catalog["entity_types"] if t["name"] == "Lease")
    assert lease["origin"] == "project" and len(catalog["changes"]) == 1
    hits = client.get("/api/graph/viz/search", params={"q": "LSB-1001"}).json()
    assert hits[0]["type"] == "Lease"
    card = client.get("/api/graph/viz/interpret", params={"id": hits[0]["id"]}).json()
    assert {l["kind"] for l in card["links"]} == {"LEASE_IN_UNIT", "LEASE_IN_COUNTY"}
    assert {f["measure"] for f in card["facts"]} == {"gross_acres", "net_acres", "royalty"}
    assert card["node"]["props"]["lessor"] and card["node"]["locator"] == "Lease Schedule!A2"
    assert card["schema"]["name"] == "Lease"
    lineage = client.get("/api/files/lease-schedule-2026-09/lineage", params={"sheet": "Lease Schedule", "cell": "H2"}).json()
    assert lineage["facts"][0]["measure"] == "gross_acres" and lineage["mapping"]["status"] == "approved"


def test_snapshot_diff_and_exports(client: TestClient) -> None:
    history = client.get("/api/snapshots").json()
    assert len(history) >= 3
    diff = client.get("/api/snapshots/diff").json()
    assert diff["entities"]["added_by_type"] == {"Lease": 124}
    assert diff["links"]["added_by_kind"]["LEASE_IN_UNIT"] == 122
    assert diff["issues"]["new_by_rule"] == {"UNMATCHED_LINK": 1}
    assert diff["after"]["catalog_version"] == "0.1.0+lone-star-basin.1" and diff["before"]["catalog_version"] == "0.1.0"
    first = client.get("/api/snapshots/diff", params={"to": history[0]["snapshot_id"]}).json()
    assert first["before"] is None
    decisions = client.get("/api/export/decisions.csv")
    assert decisions.status_code == 200 and decisions.headers["content-type"].startswith("text/csv")
    entities = client.get("/api/export/entities.csv").text
    assert "lease:lsb-1001" in entities


def test_decisions_change_the_answers(client: TestClient) -> None:
    before = client.post("/api/graph/operations/zone_summary", json={"zone": "WCA"}).json()
    assert before["data"]["pv10_musd"] is None and "not resolved" in before["summary"]
    ok = client.post("/api/issues/decision", json={"rule": "VALUE_FIELD_CONFLICT", "scope": "rule", "choice": "KY is PV-10", "reason": "seller confirmed KY is the current run", "reviewer": "finance lead"})
    assert ok.status_code == 200
    after = client.post("/api/graph/operations/zone_summary", json={"zone": "WCA"}).json()
    assert after["data"]["pv10_musd"] == round(sum(r["ky_musd"] for r in after["data"]["by_status"]), 1)
    assert "KY column" in after["summary"] and "finance lead" in after["summary"] and "not resolved" not in after["summary"]
    assert client.get("/api/room").json()["policies"]["VALUE_FIELD_CONFLICT"]["choice"] == "KY is PV-10"
    client.post("/api/issues/decision", json={"rule": "UNIT_ASSIGNMENT_CONFLICT", "scope": "rule", "choice": "Use GIS unit", "reason": "land review: the map is authoritative", "reviewer": "land lead"})
    well = client.post("/api/graph/operations/well_profile", json={"well": "JARDINE 4-27 A 4LS"}).json()
    assert well["data"]["unit"] == "GOLDEN CROSSING WEST" and "the map governs" in well["summary"] and "two unit assignments" not in well["summary"]
    answer = client.post("/api/graph/ask", json={"question": "What are the Wolfcamp A net acres, net locations and PV-10?"}).json()
    assert "KY column" in answer["answer"]
    rules = {r["code"]: r for r in client.get("/api/rules").json()}
    assert rules["VALUE_FIELD_CONFLICT"]["policy"]["choice"] == "KY is PV-10" and rules["VALUE_FIELD_CONFLICT"]["open"] == 0


def test_copying_a_project_model(client: TestClient) -> None:
    created = client.post("/api/projects", json={"name": "Follow-on Deal", "template": "copy", "copied_from": "lone-star-basin"}).json()
    assert created["model_changes"] == 1 and created["catalog_version"] == "0.1.0+follow-on-deal.1"
    changes = client.get("/api/model/changes?room=follow-on-deal").json()
    assert changes[0]["reason"] == "copied from project lone-star-basin"
    # The same lease schedule maps straight through in the new project: the header rules travelled with the model.
    uploaded = upload(client, LEASES, room="follow-on-deal")
    assert uploaded["model_proposals"] == [] and uploaded["counts"]["entities_by_type"]["Lease"] == 124
    assert uploaded["counts"]["issues_by_rule"]["UNMATCHED_LINK"] == 2  # no Unit Details here: every unit and county is unknown
    assert client.get("/api/room?room=follow-on-deal").json()["catalog_version"] == "0.1.0+follow-on-deal.1"
    assert client.delete("/api/projects/lone-star-basin").status_code == 400
    assert client.delete("/api/projects/follow-on-deal").json() == {"deleted": "follow-on-deal"}


def test_own_files_named_like_the_sample_room_fall_back_to_generic(client: TestClient, tmp_path: Path) -> None:
    """A customer's 'Unit Details' or 'ComboCurve' workbook with a different layout must not crash the built-in recipes."""
    import io
    import zipfile

    from openpyxl import Workbook

    def workbook(sheet: str, rows: list[list]) -> bytes:
        book = Workbook()
        ws = book.active
        ws.title = sheet
        for row in rows:
            ws.append(row)
        buffer = io.BytesIO()
        book.save(buffer)
        return buffer.getvalue()

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("Deal Unit Details.xlsx", workbook("Unit Details", [["Unit", "County", "Acres"], ["ALPHA", "SAGE", 640], ["BETA", "SAGE", 320]]))
        zipped.writestr("Deal ComboCurve export.xlsx", workbook("ONELINE", [["Well", "Value"], ["A-1", 10.5], ["B-2", 11.5]]))
        zipped.writestr("Maps/notes.txt", "ignored")
    created = client.post("/api/projects", json={"name": "BYOD"}).json()
    assert created["status"] == "empty"
    response = client.post("/api/uploads?room=byod", files={"file": ("room.zip", archive.getvalue(), "application/zip")})
    assert response.status_code == 200, response.text
    uploaded = response.json()
    assert sorted(uploaded["files"]) == ["combocurve", "unit-details"]  # role guessed from the names
    files = {f["file_id"]: f for f in client.get("/api/files?room=byod").json()}
    assert files["unit-details"]["role"] == "unit_details" and files["combocurve"]["role"] == "economics_oneline"
    detail = client.get("/api/files/unit-details?room=byod").json()
    assert all(table["family"] == "generic" for table in detail["tables"].values())
    assert uploaded["counts"]["entities"] == 1  # only the Asset: nothing could be keyed yet, nothing crashed
    client.delete("/api/projects/byod")


def test_mock_files_in_an_empty_project_point_at_the_base_types(client: TestClient) -> None:
    """Without the sample room, API/Unit/County columns are still recognised from their headers, and a measure is never a key."""
    client.post("/api/projects", json={"name": "Thin Room"})
    production = upload(client, ROOT / "data" / "scenarios" / "new-dataset" / "Seller Well Production_2026.07.xlsx", room="thin-room")
    key = next(p for p in production["proposals"] if p["kind"] == "key")
    assert key["header"] == "API Number" and key["target"] == "Well.api_14" and "no Well entities yet" in key["rationale"]
    # Offline, the one column the keyword heuristic cannot place is offered as a Well property; the rows stay Well rows.
    assert [p["kind"] for p in production["model_proposals"]] in ([], ["extend_entity"]) and all(p["subject"] == "Well" for p in production["model_proposals"])
    leases = upload(client, LEASES, room="thin-room")
    [proposal] = leases["model_proposals"]
    assert proposal["subject"] == "Lease"
    assert {r["relationship"]["target"] for r in proposal["items"] if r["op"] == "add_relationship"} == {"Unit", "County"}
    assert all(m["kind"] != "key" or m["header"] == "Lease No." for m in proposal["mappings"])
    client.delete("/api/projects/thin-room")
