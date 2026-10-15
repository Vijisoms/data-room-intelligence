"""Gold storage (Parquet + DuckDB per snapshot) and the in-memory snapshot used by the API."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import Any

import duckdb
import networkx as nx
import pyarrow as pa
import pyarrow.parquet as pq

from ..config import RoomPaths
from .build import Gold
from .reviews import issue_decisions

TABLES = ["nodes", "edges", "facts", "geometries", "aliases", "issues"]


def write_gold(gold_dir: Path, gold: Gold, issues: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    gold_dir.mkdir(parents=True, exist_ok=True)
    rows = {
        "nodes": [{**n, "props": json.dumps(n["props"], default=str, sort_keys=True)} for n in sorted(gold.nodes.values(), key=lambda n: n["id"])],
        "edges": [{**e, "props": json.dumps(e["props"], default=str, sort_keys=True)} for e in gold.edges],
        "facts": gold.facts,
        "geometries": gold.geometries,
        "aliases": gold.aliases,
        "issues": [
            {
                "issue_id": i["issue_id"], "rule": i["rule"], "severity": i["severity"], "subject": i["subject"], "qualifier": i.get("qualifier"),
                "detail": i["detail"], "blocks": i["blocks"], "assertions": json.dumps(i["assertions"], default=str),
                "extra": json.dumps({k: v for k, v in i.items() if k not in {"issue_id", "rule", "severity", "subject", "qualifier", "detail", "blocks", "assertions"}}, default=str),
            }
            for i in issues
        ],
    }
    for name, records in rows.items():
        table = pa.Table.from_pylist(records) if records else pa.table({"empty": pa.array([], pa.string())})
        pq.write_table(table, gold_dir / f"{name}.parquet")
    database = gold_dir / "ontology.duckdb"
    database.unlink(missing_ok=True)
    with duckdb.connect(str(database)) as con:
        for name in TABLES:
            con.execute(f"create table {name} as select * from read_parquet('{(gold_dir / f'{name}.parquet').as_posix()}')")
    counts = {
        "entities": len(gold.nodes),
        "entities_by_type": dict(sorted(Counter(n["type"] for n in gold.nodes.values()).items())),
        "relationships": len(gold.edges),
        "relationships_by_kind": dict(sorted(Counter(e["kind"] for e in gold.edges).items())),
        "facts": len(gold.facts),
        "geometries": len(gold.geometries),
        "aliases": len(gold.aliases),
        "issues": len(issues),
        "issues_by_rule": dict(sorted(Counter(i["rule"] for i in issues).items())),
    }
    snapshot = {**meta, "built_at": datetime.now(timezone.utc).isoformat(), "counts": counts}
    (gold_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return snapshot


def set_latest(room_id: str, snapshot_id: str) -> None:
    pointer = RoomPaths(room_id).latest_pointer
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps({"snapshot_id": snapshot_id}), encoding="utf-8")


def latest_snapshot_id(room_id: str) -> str | None:
    pointer = RoomPaths(room_id).latest_pointer
    return json.loads(pointer.read_text("utf-8"))["snapshot_id"] if pointer.exists() else None


def list_rooms() -> list[dict[str, Any]]:
    from ..config import data_root

    rooms = []
    for folder in sorted((data_root() / "rooms").glob("*")):
        snapshots = []
        for gold in sorted(folder.glob("snapshots/*/gold/snapshot.json")):
            meta = json.loads(gold.read_text("utf-8"))
            snapshots.append({k: meta.get(k) for k in ("snapshot_id", "status", "built_at", "catalog_version")} | {"counts": {k: meta["counts"][k] for k in ("entities", "relationships", "facts", "issues")}})
        rooms.append({"room_id": folder.name, "latest": latest_snapshot_id(folder.name), "snapshots": sorted(snapshots, key=lambda s: s["built_at"] or "")})
    return rooms


class Snapshot:
    """A published or draft snapshot loaded for queries: graph indexes, facts in DuckDB, issues with decisions."""

    def __init__(self, room_id: str, snapshot_id: str | None = None) -> None:
        self.room_id = room_id
        self.snapshot_id = snapshot_id or latest_snapshot_id(room_id)
        if not self.snapshot_id:
            raise FileNotFoundError(f"room {room_id} has no built snapshot")
        paths = RoomPaths(room_id)
        self.dir = paths.snapshot(self.snapshot_id)
        self.gold_dir = paths.gold(self.snapshot_id)
        self.silver_dir = paths.silver(self.snapshot_id)
        self.meta = json.loads((self.gold_dir / "snapshot.json").read_text("utf-8"))
        self.con = duckdb.connect()
        for name in TABLES:
            self.con.execute(f"create view {name} as select * from read_parquet('{(self.gold_dir / f'{name}.parquet').as_posix()}')")
        self.nodes: dict[str, dict[str, Any]] = {}
        for row in self.con.execute("select id, type, key, label, file, locator, props from nodes").fetchall():
            self.nodes[row[0]] = {"id": row[0], "type": row[1], "key": row[2], "label": row[3], "file": row[4], "locator": row[5], "props": json.loads(row[6])}
        self.edges = [
            {"id": r[0], "source": r[1], "kind": r[2], "target": r[3], "method": r[4], "file": r[5], "locator": r[6], "props": json.loads(r[7])}
            for r in self.con.execute("select id, source, kind, target, method, file, locator, props from edges").fetchall()
        ]
        self.out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.inn: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in self.edges:
            self.out[edge["source"]].append(edge)
            self.inn[edge["target"]].append(edge)
        self.aliases: dict[str, list[str]] = defaultdict(list)
        if "entity" in [d[0] for d in self.con.execute("select * from aliases limit 0").description]:
            for entity, alias in self.con.execute("select entity, alias from aliases").fetchall():
                self.aliases[entity].append(alias)
        self.refresh_decisions()

    def refresh_decisions(self) -> None:
        decisions = issue_decisions(self.room_id)
        by_issue = {d["issue_id"]: d for d in decisions if d["scope"] == "issue"}
        by_rule = {d["rule"]: d for d in decisions if d["scope"] == "rule"}
        self.issues: list[dict[str, Any]] = []
        for row in self.con.execute("select issue_id, rule, severity, subject, qualifier, detail, blocks, assertions, extra from issues").fetchall():
            issue = {"issue_id": row[0], "rule": row[1], "severity": row[2], "subject": row[3], "qualifier": row[4], "detail": row[5], "blocks": row[6], "assertions": json.loads(row[7]), **json.loads(row[8])}
            decision = by_issue.get(issue["issue_id"]) or by_rule.get(issue["rule"])
            issue["status"] = "decided" if decision else "open"
            issue["decision"] = decision
            self.issues.append(issue)
        self.issues_by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for issue in self.issues:
            self.issues_by_subject[issue["subject"]].append(issue)
        self.issue_index = {issue["issue_id"]: issue for issue in self.issues}

    @cached_property
    def graph(self) -> nx.MultiDiGraph:
        graph = nx.MultiDiGraph()
        for node in self.nodes.values():
            graph.add_node(node["id"], type=node["type"], label=node["label"])
        for edge in self.edges:
            graph.add_edge(edge["source"], edge["target"], key=edge["id"], kind=edge["kind"], method=edge["method"])
        return graph

    def facts(self, subject: str | None = None, measure: str | None = None, **dims: Any) -> list[dict[str, Any]]:
        clauses, params = [], []
        for column, value in (("subject", subject), ("measure", measure), *dims.items()):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = f"where {' and '.join(clauses)}" if clauses else ""
        cursor = self.con.execute(f"select * from facts {where}", params)
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def sql(self, query: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        return self.con.execute(query, params or []).fetchall()

    @cached_property
    def documents(self) -> dict[str, dict[str, Any]]:
        return {p.parent.name: json.loads(p.read_text("utf-8")) for p in sorted((self.silver_dir / "documents").glob("*/document.json"))}

    @cached_property
    def manifest(self) -> dict[str, Any]:
        return json.loads((self.dir / "bronze" / "manifest.json").read_text("utf-8"))

    @cached_property
    def schemas(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted((self.silver_dir / "schemas").glob("*.json")):
            items.extend(json.loads(path.read_text("utf-8")))
        return items

    @cached_property
    def tables(self) -> dict[str, dict[str, Any]]:
        path = self.silver_dir / "tabular" / "tables.json"
        return {t["dataset_id"]: t for t in json.loads(path.read_text("utf-8"))} if path.exists() else {}

    @cached_property
    def sheets(self) -> list[dict[str, Any]]:
        path = self.silver_dir / "tabular" / "sheets.json"
        return json.loads(path.read_text("utf-8")) if path.exists() else []

    @cached_property
    def mappings(self) -> list[dict[str, Any]]:
        path = self.silver_dir / "mappings.json"
        return json.loads(path.read_text("utf-8")) if path.exists() else []
