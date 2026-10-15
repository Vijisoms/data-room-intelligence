"""Append-only review decisions for issues and field mappings (reviews/*.jsonl per room)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import RoomPaths


def _append(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")
    return record


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def record_issue_decision(room_id: str, issue_id: str, rule: str, choice: str, reason: str, reviewer: str, snapshot_id: str, scope: str = "issue") -> dict[str, Any]:
    if not reason.strip():
        raise ValueError("a decision needs a reason")
    return _append(
        RoomPaths(room_id).reviews / "decisions.jsonl",
        {
            "decision_id": f"decision:{uuid.uuid4().hex[:12]}",
            "issue_id": issue_id,
            "rule": rule,
            "scope": scope,
            "choice": choice,
            "reason": reason.strip(),
            "reviewer": reviewer,
            "snapshot_id": snapshot_id,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def issue_decisions(room_id: str) -> list[dict[str, Any]]:
    return _read(RoomPaths(room_id).reviews / "decisions.jsonl")


def record_mapping_decision(room_id: str, mapping: dict[str, Any], status: str, reviewer: str, reason: str = "") -> dict[str, Any]:
    if status not in {"approved", "rejected"}:
        raise ValueError("status must be approved or rejected")
    return _append(
        RoomPaths(room_id).reviews / "mapping-decisions.jsonl",
        {**mapping, "status": status, "decided_by": reviewer, "reason": reason, "decided_at": datetime.now(timezone.utc).isoformat()},
    )


def mapping_decisions(room_id: str) -> dict[tuple[str, str], dict[str, Any]]:
    """Latest decision per (normalized header, target): approved headers are remembered across files."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for record in _read(RoomPaths(room_id).reviews / "mapping-decisions.jsonl"):
        latest[(record["header_key"], record["target"])] = record
    return latest
