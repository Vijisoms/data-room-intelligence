"""FastAPI service: graph exploration, file viewers, review, mappings, uploads and chat."""

from __future__ import annotations

import json
import os
import re
import threading
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import REPO_ROOT, RoomPaths, offline, slug
from ..ingest.families import load_grids
from ..ontology.catalog import load_aliases, load_catalog, load_rules
from ..ontology.mapping import header_key
from ..ontology.pipeline import publish
from ..ontology.reviews import record_issue_decision, record_mapping_decision
from ..ontology.store import Snapshot, list_rooms
from . import chat, operations as ops

ROOM_ID = os.environ.get("DATA_ROOM_ASSET_ID", "lone-star-basin")
ROOM_DIR = Path(os.environ.get("DATA_ROOM_PATH", REPO_ROOT / "data" / "sample-room"))
UPLOAD_TYPES = {".xlsx", ".csv"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
TYPE_ORDER = [t.name for t in load_catalog().entity_types]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    scope: str | None = None


class IssueDecision(BaseModel):
    issue_id: str | None = None
    rule: str
    scope: str = Field(default="issue", pattern="^(issue|rule)$")
    choice: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=1000)
    reviewer: str = Field(default="reviewer", max_length=80)


class MappingDecision(BaseModel):
    field_id: str
    target: str
    status: str = Field(pattern="^(approved|rejected)$")
    reviewer: str = Field(default="reviewer", max_length=80)
    reason: str = Field(default="", max_length=1000)


class PublishRequest(BaseModel):
    reviewer: str | None = None
    reason: str | None = None
    force: bool = False


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self._snapshot: Snapshot | None = None

    @property
    def snapshot(self) -> Snapshot:
        if self._snapshot is None:
            try:
                self._snapshot = Snapshot(ROOM_ID)
            except FileNotFoundError as error:
                raise HTTPException(503, f"No snapshot built yet: run `data-room-intel snapshot` ({error})") from error
        return self._snapshot

    def reload(self) -> Snapshot:
        self._snapshot = None
        _grids.cache_clear()
        return self.snapshot


state = State()
app = FastAPI(title="Data Room Intelligence", version="0.1.0")


@lru_cache(maxsize=6)
def _grids(snapshot_id: str, file_id: str) -> dict[str, Any]:
    snap = state.snapshot
    entry = _entry(snap, file_id)
    return {grid.name: grid for grid in load_grids(snap.dir / "bronze" / "originals" / entry["path"])}


def _entry(snap: Snapshot, file_id: str) -> dict[str, Any]:
    entry = next((f for f in snap.manifest["files"] if f["file_id"] == file_id), None)
    if entry is None:
        raise HTTPException(404, f"unknown file {file_id}")
    return entry


def _issue_counts(snap: Snapshot, entity: str) -> dict[str, int]:
    return dict(Counter(i["severity"] for i in snap.issues_by_subject.get(entity, []) if i["status"] == "open"))


def _conflict_edges(snap: Snapshot) -> set[str]:
    edges = set()
    for issue in snap.issues:
        if issue["rule"] != "UNIT_ASSIGNMENT_CONFLICT" or issue["status"] != "open":
            continue
        well = issue["subject"]
        edges.update(e["id"] for e in snap.out.get(well, []) if e["kind"] == "LATERAL_IN_UNIT")
        for link in (e for e in snap.inn.get(well, []) if e["kind"] == "IS_WELL"):
            edges.update(e["id"] for e in snap.out.get(link["source"], []) if e["kind"] == "ASSIGNED_TO_UNIT")
    return edges


def _node_card(snap: Snapshot, node: dict[str, Any], level: int | None = None) -> dict[str, Any]:
    props = {k: v for k, v in node["props"].items() if k not in {"raw"}}
    return {"id": node["id"], "type": node["type"], "label": node["label"], "level": level, "issues": _issue_counts(snap, node["id"]), "props": props}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "offline": offline(), "model": None if offline() else os.environ.get("FOUNDRY_MODEL"), "room_id": ROOM_ID}


@app.get("/api/rooms")
def rooms() -> list[dict[str, Any]]:
    return list_rooms()


@app.get("/api/room")
def room() -> dict[str, Any]:
    snap = state.snapshot
    open_issues = [i for i in snap.issues if i["status"] == "open"]
    return {
        **{k: snap.meta.get(k) for k in ("room_id", "snapshot_id", "status", "catalog_version", "rules_version", "built_at", "files", "mappings", "counts")},
        "name": next((n["label"] for n in snap.nodes.values() if n["type"] == "Asset"), ROOM_ID),
        "open_issues": dict(Counter(i["severity"] for i in open_issues)),
        "decided_issues": len(snap.issues) - len(open_issues),
    }


@app.get("/api/catalog")
def catalog() -> dict[str, Any]:
    snap = state.snapshot
    kinds = Counter(e["kind"] for e in snap.edges)
    types = Counter(n["type"] for n in snap.nodes.values())
    rules = load_rules()
    return {
        **load_catalog().model_dump(mode="json"),
        "rules": [{**r.model_dump(mode="json"), "count": sum(i["rule"] == r.code for i in snap.issues)} for r in rules.rules],
        "aliases": {name: table.model_dump(mode="json") for name, table in load_aliases().items()},
        "counts": {"entities": dict(types), "relationships": dict(kinds)},
    }


@app.get("/api/graph/stats")
def graph_stats() -> dict[str, Any]:
    return state.snapshot.meta["counts"]


@app.get("/api/graph/operations")
def graph_operations() -> dict[str, str]:
    return ops.OPERATIONS


@app.get("/api/graph/gaps")
def graph_gaps() -> dict[str, Any]:
    return ops.gap_report(state.snapshot)


@app.get("/api/graph/viz/schema")
def viz_schema() -> dict[str, Any]:
    snap = state.snapshot
    types = Counter(n["type"] for n in snap.nodes.values())
    issues = defaultdict(Counter)
    for issue in snap.issues:
        if issue["status"] == "open":
            issues[snap.nodes[issue["subject"]]["type"]][issue["severity"]] += 1
    links = Counter((snap.nodes[e["source"]]["type"], e["kind"], snap.nodes[e["target"]]["type"], e["method"]) for e in snap.edges)
    catalog_ = load_catalog()
    declared = {r.name for r in catalog_.relationship_types}
    gaps = [{"source": r.source, "kind": r.name, "target": r.target, "method": r.method, "count": 0} for r in catalog_.relationship_types if r.name not in {k for _, k, _, _ in links}]
    return {
        "types": [{"type": t, "count": types.get(t, 0), "issues": dict(issues.get(t, {}))} for t in TYPE_ORDER],
        "links": [{"source": s, "kind": k, "target": t, "method": m, "count": c} for (s, k, t, m), c in sorted(links.items())] + gaps,
        "declared": sorted(declared),
    }


@app.get("/api/graph/viz/search")
def viz_search(q: str = Query(min_length=1, max_length=100), limit: int = Query(30, le=100)) -> list[dict[str, Any]]:
    snap = state.snapshot
    text = q.strip().lower()
    digits = re.sub(r"\D", "", text)
    hits = []
    for node in snap.nodes.values():
        names = [node["label"].lower(), node["id"].lower(), *(a.lower() for a in snap.aliases.get(node["id"], []))]
        score = 100 if text in names else 70 if any(n.startswith(text) for n in names) else 40 if any(text in n for n in names) else 0
        if not score and len(digits) >= 6 and node["type"] == "Well" and digits in node["props"].get("api_14", ""):
            score = 80
        if score:
            hits.append((score + (1 if snap.issues_by_subject.get(node["id"]) else 0) - TYPE_ORDER.index(node["type"]) * 0.01, node))
    return [_node_card(snap, node) | {"score": round(score, 2)} for score, node in sorted(hits, key=lambda h: -h[0])[:limit]]


@app.get("/api/graph/viz/neighborhood")
def viz_neighborhood(id: str, depth: int = Query(2, ge=1, le=2), types: str | None = None, methods: str | None = None, issues_only: bool = False) -> dict[str, Any]:
    snap = state.snapshot
    if id not in snap.nodes:
        raise HTTPException(404, f"unknown entity {id}")
    allowed_types = set(types.split(",")) if types else set(TYPE_ORDER)
    allowed_methods = set(methods.split(",")) if methods else {"source", "key", "spatial", "alias", "document", "crosswalk"}
    conflict = _conflict_edges(snap)
    visible = lambda e: e["method"] in allowed_methods or e["id"] in conflict  # noqa: E731
    level, parents = {id: 0}, {}
    frontier = [id]
    hub = len(snap.out.get(id, [])) + len(snap.inn.get(id, [])) > 60
    depth = 1 if hub else depth
    for d in range(1, depth + 1):
        nxt = []
        for current in frontier:
            for edge in [*snap.out.get(current, []), *snap.inn.get(current, [])]:
                other = edge["target"] if edge["source"] == current else edge["source"]
                if not visible(edge) or snap.nodes[other]["type"] not in allowed_types:
                    continue
                if other not in level:
                    level[other], parents[other] = d, [current]
                    nxt.append(other)
                elif level[other] == d:
                    parents[other].append(current)
        frontier = nxt
    caps = {1: 28, 2: 10}
    keep, capped = {id}, 0
    for d in (1, 2):
        groups = defaultdict(list)
        for node_id, l in level.items():
            if l == d:
                groups[snap.nodes[node_id]["type"]].append(node_id)
        for members in groups.values():
            has_issue = lambda n: bool(_issue_counts(snap, n))  # noqa: E731
            members.sort(key=lambda n: (not has_issue(n), -len(parents.get(n, [])), n))
            pool = [m for m in members if has_issue(m)] if issues_only and d == 2 else members
            chosen = [m for m in pool[: caps[d]] if d == 1 or any(p in keep for p in parents[m])]
            keep.update(chosen)
            capped += len(members) - len(chosen)
    edges = [e for e in snap.edges if e["source"] in keep and e["target"] in keep and visible(e)]
    return {
        "focus": id,
        "depth": depth,
        "hub": hub,
        "capped": capped,
        "nodes": [_node_card(snap, snap.nodes[n], level[n]) | {"parents": parents.get(n, [])} for n in sorted(keep, key=lambda n: (level[n], TYPE_ORDER.index(snap.nodes[n]["type"]), snap.nodes[n]["label"]))],
        "edges": [{"id": e["id"], "source": e["source"], "target": e["target"], "kind": e["kind"], "method": e["method"], "conflict": e["id"] in conflict, "evidence": e["locator"], "file": e["file"], "props": e["props"]} for e in edges],
    }


@app.get("/api/graph/viz/interpret")
def viz_interpret(id: str) -> dict[str, Any]:
    snap = state.snapshot
    node = snap.nodes.get(id)
    if node is None:
        raise HTTPException(404, f"unknown entity {id}")
    conflict = _conflict_edges(snap)
    links = []
    for edge, direction in [*((e, "out") for e in snap.out.get(id, [])), *((e, "in") for e in snap.inn.get(id, []))]:
        other = snap.nodes[edge["target"] if direction == "out" else edge["source"]]
        links.append({"direction": direction, "kind": edge["kind"], "method": edge["method"], "file": edge["file"], "locator": edge["locator"], "props": edge["props"], "conflict": edge["id"] in conflict, "other": _node_card(snap, other)})
    facts = snap.facts(id)
    geometry = snap.sql("select kind, wkb from geometries where entity = ?", [id])
    from shapely import from_wkb
    from shapely.geometry import mapping as geo_mapping

    entity_type = load_catalog().entity(node["type"])
    return {
        "node": _node_card(snap, node) | {"file": node["file"], "locator": node["locator"], "props": node["props"]},
        "aliases": snap.aliases.get(id, []),
        "links": links[:400],
        "link_count": len(links),
        "facts": facts[:600],
        "fact_count": len(facts),
        "issues": snap.issues_by_subject.get(id, []),
        "geometry": [geo_mapping(from_wkb(row[1])) for row in geometry],
        "schema": entity_type.model_dump(mode="json"),
        "measures": [m.model_dump(mode="json") for m in load_catalog().measures if m.subject == node["type"]],
    }


@app.post("/api/graph/ask")
async def graph_ask(request: AskRequest) -> dict[str, Any]:
    return await chat.ask(state.snapshot, request.question, request.scope)


@app.get("/api/files")
def files() -> list[dict[str, Any]]:
    snap = state.snapshot
    by_file = defaultdict(Counter)
    for issue in snap.issues:
        for assertion in issue["assertions"]:
            if assertion.get("file"):
                by_file[assertion["file"]][issue["rule"]] += 1
    sheets = defaultdict(list)
    for sheet in snap.sheets:
        sheets[sheet["file_id"]].append(sheet)
    items = []
    for entry in snap.manifest["files"]:
        if entry["kind"] == "gis_sidecar":
            continue
        document = snap.documents.get(entry["file_id"])
        items.append({
            **{k: entry[k] for k in ("file_id", "path", "kind", "role", "size_bytes", "sha256", "as_of", "protection", "bundle")},
            "sidecars": sum(1 for f in snap.manifest["files"] if f["bundle"] == entry["bundle"] and f["kind"] == "gis_sidecar") if entry["bundle"] else 0,
            "sheets": [{k: s[k] for k in ("sheet", "rows", "columns", "filled_cells", "formula_cells", "uncached_formulas")} for s in sheets.get(entry["file_id"], [])],
            "pages": len(document["pages"]) if document else None,
            "figures": len(document["figures"]) if document else None,
            "claims": len(document["claims"]) if document else None,
            "issues": dict(by_file.get(entry["path"], {})),
            "incoming": entry["path"].startswith("incoming/"),
        })
    return items


@app.get("/api/files/{file_id}")
def file_detail(file_id: str) -> dict[str, Any]:
    snap = state.snapshot
    entry = _entry(snap, file_id)
    datasets = [s for s in snap.schemas if s["file"] == entry["path"]]
    tables = {d: t for d, t in snap.tables.items() if t["file_id"] == file_id}
    mappings = [m for m in snap.mappings if m["file"] == entry["path"]]
    return {"entry": entry, "datasets": datasets, "tables": tables, "mappings": mappings, "document": snap.documents.get(file_id)}


@app.get("/api/files/{file_id}/grid")
def file_grid(file_id: str, sheet: str, r0: int = Query(1, ge=1), r1: int = Query(60, ge=1), c0: int = Query(1, ge=1), c1: int = Query(30, ge=1)) -> dict[str, Any]:
    snap = state.snapshot
    grids = _grids(snap.snapshot_id, file_id)
    grid = grids.get(sheet)
    if grid is None:
        raise HTTPException(404, f"unknown sheet {sheet}")
    r1, c1 = min(r1, r0 + 400, grid.max_row), min(c1, c0 + 80, grid.max_col)

    def cell(r: int, c: int) -> Any:
        value = grid.get(r, c)
        return value.isoformat()[:10] if hasattr(value, "isoformat") else value

    return {
        "sheet": sheet, "max_row": grid.max_row, "max_col": grid.max_col, "r0": r0, "r1": r1, "c0": c0, "c1": c1,
        "rows": [[cell(r, c) for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)],
        "formulas": [[c for c in range(c0, c1 + 1) if grid.formula(r, c)] for r in range(r0, r1 + 1)],
    }


@app.get("/api/files/{file_id}/lineage")
def cell_lineage(file_id: str, sheet: str, cell: str = Query(pattern=r"^[A-Z]{1,3}\d{1,6}$")) -> dict[str, Any]:
    snap = state.snapshot
    path = _entry(snap, file_id)["path"]
    locator = f"{sheet}!{cell}"
    facts = snap.sql("select subject, measure, value, unit, zone, period, item, quality from facts where file = ? and locator = ?", [path, locator])
    edges = [e for e in snap.edges if e["file"] == path and e["locator"] == locator]
    nodes = [n for n in snap.nodes.values() if n["file"] == path and n["locator"] == locator]
    row = int(re.sub(r"\D", "", cell))
    entities = {f[0] for f in facts} | {e["source"] for e in edges} | {n["id"] for n in nodes}
    if not entities:
        row_pattern = re.compile(rf"^{re.escape(sheet)}![A-Z]+{row}$")
        entities = {n["id"] for n in snap.nodes.values() if n["file"] == path and n["locator"] and row_pattern.match(n["locator"])}
        if not entities:
            entities = {s for s, loc in snap.sql("select distinct subject, locator from facts where file = ? and locator like ?", [path, f"{sheet}!%{row}"]) if row_pattern.match(loc)}
    mapping = next((m for m in snap.mappings if m["file"] == path and m["column"] == re.sub(r"\d", "", cell) and snap.tables.get(m["dataset_id"], {}).get("sheet") == sheet), None)
    return {
        "locator": locator,
        "facts": [dict(zip(["subject", "measure", "value", "unit", "zone", "period", "item", "quality"], f)) for f in facts],
        "links": [{"kind": e["kind"], "source": e["source"], "target": e["target"], "method": e["method"]} for e in edges],
        "entities": [_node_card(snap, snap.nodes[e]) for e in sorted(entities) if e in snap.nodes],
        "mapping": mapping,
        "issues": [i for e in entities for i in snap.issues_by_subject.get(e, []) if any(a.get("locator") == locator for a in i["assertions"])][:10],
    }


@app.get("/api/files/{file_id}/pages/{page}.png")
def page_image(file_id: str, page: int) -> FileResponse:
    snap = state.snapshot
    path = snap.silver_dir / "documents" / file_id / "pages" / f"page-{page}.png"
    if file_id not in snap.documents or not path.exists():
        raise HTTPException(404, "page not found")
    return FileResponse(path, media_type="image/png")


@app.get("/api/files/{file_id}/figures/{figure_id}.png")
def figure_image(file_id: str, figure_id: str) -> FileResponse:
    snap = state.snapshot
    if file_id not in snap.documents or not re.fullmatch(r"[\d.]+", figure_id):
        raise HTTPException(404, "figure not found")
    path = snap.silver_dir / "documents" / file_id / "figures" / f"figure-{figure_id}.png"
    if not path.exists():
        raise HTTPException(404, "figure not found")
    return FileResponse(path, media_type="image/png")


@app.get("/api/layers/{file_id}")
def layer(file_id: str) -> JSONResponse:
    snap = state.snapshot
    _entry(snap, file_id)
    path = snap.silver_dir / "gis" / f"{file_id}.geojson"
    if not path.exists():
        raise HTTPException(404, "layer not found")
    data = json.loads(path.read_text("utf-8"))
    prefix = {"gis-pdp": "well", "gis-leasehold": "tract", "gis-units-pf": "unit", "gis-units": "unit"}.get(file_id)
    for feature in data["features"]:
        fid = str(feature["properties"]["feature_id"])
        entity = f"{prefix}:{fid[2:]}" if fid.startswith("g-") else f"{prefix}:{fid}" if prefix == "well" else f"{prefix}:{slug(fid)}"
        feature["properties"] = {"entity": entity if entity in snap.nodes else None, "issues": _issue_counts(snap, entity), **feature["properties"]}
    return JSONResponse(data)


@app.get("/api/issues")
def issues(rule: str | None = None, subject: str | None = None, status: str | None = None, limit: int = Query(200, le=2000), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    snap = state.snapshot
    selected = [i for i in snap.issues if (not rule or i["rule"] == rule) and (not subject or i["subject"] == subject) and (not status or i["status"] == status)]
    page = selected[offset: offset + limit]
    return {"total": len(selected), "items": [i | {"subject_label": snap.nodes[i["subject"]]["label"], "subject_type": snap.nodes[i["subject"]]["type"]} for i in page]}


@app.get("/api/rules")
def rules() -> list[dict[str, Any]]:
    snap = state.snapshot
    counts = defaultdict(Counter)
    for issue in snap.issues:
        counts[issue["rule"]][issue["status"]] += 1
    return [{**r.model_dump(mode="json"), "open": counts[r.code]["open"], "decided": counts[r.code]["decided"]} for r in load_rules().rules if counts[r.code]]


@app.post("/api/issues/decision")
def issue_decision(decision: IssueDecision) -> dict[str, Any]:
    snap = state.snapshot
    if decision.scope == "issue" and decision.issue_id not in snap.issue_index:
        raise HTTPException(404, "unknown issue")
    record = record_issue_decision(snap.room_id, decision.issue_id or f"rule:{decision.rule}", decision.rule, decision.choice, decision.reason, decision.reviewer, snap.snapshot_id, decision.scope)
    snap.refresh_decisions()
    return record


@app.post("/api/publish")
def publish_snapshot(request: PublishRequest) -> dict[str, Any]:
    outcome = publish(ROOM_ID, reviewer=request.reviewer, reason=request.reason, force=request.force)
    state.reload()
    return outcome


@app.get("/api/mappings")
def mappings(status: str | None = None, file_id: str | None = None) -> list[dict[str, Any]]:
    snap = state.snapshot
    path = _entry(snap, file_id)["path"] if file_id else None
    return [m for m in snap.mappings if (not status or m["status"] == status) and (not path or m["file"] == path)]


@app.post("/api/mappings/decision")
def mapping_decision(decision: MappingDecision) -> dict[str, Any]:
    snap = state.snapshot
    proposal = next((m for m in snap.mappings if m["field_id"] == decision.field_id and m["target"] == decision.target), None)
    if proposal is None:
        raise HTTPException(404, "unknown mapping proposal")
    record = record_mapping_decision(snap.room_id, {k: proposal[k] for k in ("field_id", "header", "target", "kind", "method")} | {"header_key": header_key(proposal["header"])}, decision.status, decision.reviewer, decision.reason)
    proposal.update({"status": decision.status, "decided_by": decision.reviewer})
    return record


@app.post("/api/rebuild")
async def rebuild() -> dict[str, Any]:
    from ..azure_services import azure_options, mapping_model
    from ..ontology.runner import BuildRequest, ReviewResponse, run_ontology_workflow

    result = await run_ontology_workflow(BuildRequest(ROOM_ID, str(ROOM_DIR)), {**azure_options(), "mapping_model": mapping_model()}, ReviewResponse("hold"))
    snap = state.reload()
    return {"snapshot_id": result.snapshot_id, "status": snap.meta["status"], "counts": snap.meta["counts"], "mappings": snap.meta.get("mappings")}


@app.post("/api/uploads")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    name = Path(file.filename or "").name
    if not name or Path(name).suffix.lower() not in UPLOAD_TYPES or name.startswith((".", "~$")):
        raise HTTPException(400, f"upload a {' or '.join(sorted(UPLOAD_TYPES))} file")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file is larger than 20 MB")
    target = RoomPaths(ROOM_ID).incoming / re.sub(r"[^A-Za-z0-9 ._()-]", "_", name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    rebuilt = await rebuild()
    snap = state.snapshot
    entry = next(f for f in snap.manifest["files"] if f["path"] == f"incoming/{target.name}")
    return {**rebuilt, "file_id": entry["file_id"], "proposals": [m for m in snap.mappings if m["file"] == entry["path"]]}


FRONTEND = REPO_ROOT / "frontend" / "dist"
if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (FRONTEND / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(FRONTEND.resolve()):
            return FileResponse(candidate)
        return FileResponse(FRONTEND / "index.html")
