"""Build a snapshot: Silver -> mappings -> Gold -> rules, and the publish gate."""

from __future__ import annotations

import json
from typing import Any

from ..config import RoomPaths
from ..ingest.run import PIPELINE_VERSION, IngestContext
from .build import Silver, build
from .catalog import load_aliases, load_catalog, load_rules
from .mapping import apply_approved, propose
from .reviews import mapping_decisions
from .store import Snapshot, set_latest, write_gold


async def build_gold(ctx: IngestContext, client_factory: Any = None, model: str | None = None, room_name: str = "Lone Star Basin") -> dict[str, Any]:
    catalog, rules, aliases = load_catalog(), load_rules(), load_aliases()
    silver = Silver(ctx.silver)
    gold = build(ctx.silver, catalog, aliases, room_name)
    proposals = await propose(silver, gold, catalog, mapping_decisions(ctx.room_id), client_factory, model)
    (ctx.silver / "mappings.json").write_text(json.dumps(proposals, indent=1, default=str), encoding="utf-8")
    from .rules import evaluate

    issues = evaluate(gold, rules, apply_approved(silver, gold, proposals, rules, catalog))
    blocking = sum(issue["severity"] == "blocking" for issue in issues)
    meta = {
        "room_id": ctx.room_id,
        "snapshot_id": ctx.snapshot_id,
        "status": "in_review" if blocking else "ready",
        "catalog_version": catalog.catalog_version,
        "rules_version": rules.rules_version,
        "pipeline_version": PIPELINE_VERSION,
        "files": len(ctx.manifest.files),
        "mappings": {"approved": sum(p["status"] == "approved" for p in proposals), "proposed": sum(p["status"] == "proposed" for p in proposals)},
    }
    snapshot = write_gold(RoomPaths(ctx.room_id).gold(ctx.snapshot_id), gold, issues, meta)
    set_latest(ctx.room_id, ctx.snapshot_id)
    return snapshot


def publish(room_id: str, snapshot_id: str | None = None, reviewer: str | None = None, reason: str | None = None, force: bool = False) -> dict[str, Any]:
    """Publish when no blocking issue is open; forcing needs a reviewer and a reason."""
    snapshot = Snapshot(room_id, snapshot_id)
    open_blocking = [i for i in snapshot.issues if i["severity"] == "blocking" and i["status"] == "open"]
    if open_blocking and not (force and reviewer and reason):
        return {"published": False, "snapshot_id": snapshot.snapshot_id, "open_blocking": len(open_blocking), "rules": sorted({i["rule"] for i in open_blocking})}
    path = snapshot.gold_dir / "snapshot.json"
    meta = json.loads(path.read_text("utf-8"))
    meta.update({"status": "published", "published_by": reviewer, "publish_reason": reason, "open_blocking_at_publish": len(open_blocking)})
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"published": True, "snapshot_id": snapshot.snapshot_id, "open_blocking": len(open_blocking)}
