"""What changed between two snapshots of a project: files, entities, links, facts and issues.

Entity IDs, link IDs and issue IDs are deterministic, so two snapshots can be compared by key: a well that
appears in both is the same well, and a decision recorded against an issue keeps applying when the issue
reappears. Fact values are compared on (subject, measure, dimensions)."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import duckdb

from ..config import RoomPaths

SAMPLE = 8
DIMENSIONS = ["subject", "measure", "zone", "period", "item", "section", "case_id"]


def _gold(room_id: str, snapshot_id: str, table: str) -> str:
    return RoomPaths(room_id).gold(snapshot_id).joinpath(f"{table}.parquet").as_posix()


def _manifest(room_id: str, snapshot_id: str) -> dict[str, Any]:
    return json.loads((RoomPaths(room_id).bronze(snapshot_id) / "manifest.json").read_text("utf-8"))


def _meta(room_id: str, snapshot_id: str) -> dict[str, Any]:
    return json.loads((RoomPaths(room_id).gold(snapshot_id) / "snapshot.json").read_text("utf-8"))


def snapshot_diff(room_id: str, before: str, after: str) -> dict[str, Any]:
    con = duckdb.connect()
    a, b = before, after

    def side(table: str, columns: str, key: str, which: str) -> list[tuple[Any, ...]]:
        left, right = (b, a) if which == "added" else (a, b)
        return con.execute(
            f"select {columns} from read_parquet('{_gold(room_id, left, table)}') l where not exists (select 1 from read_parquet('{_gold(room_id, right, table)}') r where r.{key} = l.{key})"
        ).fetchall()

    files_before = {f["path"]: f for f in _manifest(room_id, a)["files"] if f["kind"] != "gis_sidecar"}
    files_after = {f["path"]: f for f in _manifest(room_id, b)["files"] if f["kind"] != "gis_sidecar"}
    files = {
        "added": sorted(set(files_after) - set(files_before)),
        "removed": sorted(set(files_before) - set(files_after)),
        "changed": sorted(p for p in set(files_before) & set(files_after) if files_before[p]["sha256"] != files_after[p]["sha256"]),
    }
    nodes_added = side("nodes", "id, type, label", "id", "added")
    nodes_removed = side("nodes", "id, type, label", "id", "removed")
    edges_added = side("edges", "id, kind", "id", "added")
    edges_removed = side("edges", "id, kind", "id", "removed")
    issues_new = side("issues", "issue_id, rule, severity, subject, detail", "issue_id", "added")
    issues_gone = side("issues", "issue_id, rule, severity, subject, detail", "issue_id", "removed")
    dims = " and ".join(f"coalesce(cast(l.{d} as varchar), '') = coalesce(cast(r.{d} as varchar), '')" for d in DIMENSIONS)
    changed = con.execute(
        f"select l.subject, l.measure, l.zone, l.period, l.item, l.value, r.value, r.locator from read_parquet('{_gold(room_id, a, 'facts')}') l "
        f"join read_parquet('{_gold(room_id, b, 'facts')}') r on {dims} where l.value is distinct from r.value"
    ).fetchall()
    facts_before = con.execute(f"select count(*) from read_parquet('{_gold(room_id, a, 'facts')}')").fetchone()[0]
    facts_after = con.execute(f"select count(*) from read_parquet('{_gold(room_id, b, 'facts')}')").fetchone()[0]
    group = lambda rows, index: dict(sorted(Counter(r[index] for r in rows).items()))  # noqa: E731
    return {
        "before": {"snapshot_id": a, **{k: _meta(room_id, a).get(k) for k in ("built_at", "catalog_version", "status")}},
        "after": {"snapshot_id": b, **{k: _meta(room_id, b).get(k) for k in ("built_at", "catalog_version", "status")}},
        "files": files,
        "entities": {
            "added": len(nodes_added), "removed": len(nodes_removed),
            "added_by_type": group(nodes_added, 1), "removed_by_type": group(nodes_removed, 1),
            "added_sample": [{"id": r[0], "type": r[1], "label": r[2]} for r in nodes_added[:SAMPLE]],
            "removed_sample": [{"id": r[0], "type": r[1], "label": r[2]} for r in nodes_removed[:SAMPLE]],
        },
        "links": {"added": len(edges_added), "removed": len(edges_removed), "added_by_kind": group(edges_added, 1), "removed_by_kind": group(edges_removed, 1)},
        "facts": {
            "before": facts_before, "after": facts_after, "changed": len(changed),
            "changed_sample": [{"subject": r[0], "measure": r[1], "zone": r[2], "period": r[3], "item": r[4], "before": r[5], "after": r[6], "locator": r[7]} for r in changed[:SAMPLE]],
        },
        "issues": {
            "new": len(issues_new), "resolved": len(issues_gone),
            "new_by_rule": group(issues_new, 1), "resolved_by_rule": group(issues_gone, 1),
            "new_sample": [{"issue_id": r[0], "rule": r[1], "severity": r[2], "subject": r[3], "detail": r[4]} for r in issues_new[:SAMPLE]],
            "resolved_sample": [{"issue_id": r[0], "rule": r[1], "severity": r[2], "subject": r[3], "detail": r[4]} for r in issues_gone[:SAMPLE]],
        },
    }
