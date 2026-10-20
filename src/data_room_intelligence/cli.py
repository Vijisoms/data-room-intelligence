from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .doctor import format_checks, run_doctor


def parser() -> argparse.ArgumentParser:
    data_room = Path(os.environ.get("DATA_ROOM_PATH", "data/sample-room"))
    room_id = os.environ.get("DATA_ROOM_ASSET_ID", "lone-star-basin")
    root = argparse.ArgumentParser(prog="data-room-intel")
    commands = root.add_subparsers(dest="command", required=True)
    ask = commands.add_parser("ask", help="Ask a question; answered by named operations over the latest snapshot")
    ask.add_argument("question")
    ask.add_argument("--room-id", default=room_id)
    doctor = commands.add_parser(
        "doctor", help="Check the data room, Azure identity, Foundry models and Document Intelligence"
    )
    doctor.add_argument("--data-room", type=Path, default=data_room)
    catalog = commands.add_parser("catalog", help="Validate the ontology catalog or export review artifacts")
    catalog.add_argument("action", choices=["validate", "export"])
    catalog.add_argument("--out", type=Path, default=Path("docs/catalog"))
    ingest = commands.add_parser("ingest", help="Discover the room and extract GIS, tables and PDFs into Silver")
    ingest.add_argument("data_room", type=Path, nargs="?", default=data_room)
    ingest.add_argument("--room-id", default=room_id)
    snapshot = commands.add_parser("snapshot", help="Run the ontology workflow: discover, extract in parallel, build, reconcile, review gate")
    snapshot.add_argument("data_room", type=Path, nargs="?", default=data_room)
    snapshot.add_argument("--room-id", default=room_id)
    publish = commands.add_parser("publish-snapshot", help="Publish the latest snapshot if no blocking issue is open")
    publish.add_argument("--room-id", default=room_id)
    publish.add_argument("--reviewer")
    publish.add_argument("--reason")
    publish.add_argument("--force", action="store_true", help="Publish with open blocking issues (needs --reviewer and --reason)")
    serve = commands.add_parser("serve", help="Run the API and web UI on localhost")
    serve.add_argument("--port", type=int, default=8000)
    return root


async def _run(args: argparse.Namespace) -> None:
    if args.command == "serve":
        import uvicorn

        config = uvicorn.Config("data_room_intelligence.service.api:app", host="127.0.0.1", port=args.port, log_level="info")
        await uvicorn.Server(config).serve()
        return
    if args.command == "snapshot":
        from .azure_services import azure_options, mapping_model
        from .ontology.projects import ensure_project
        from .ontology.runner import BuildRequest, run_ontology_workflow

        ensure_project(args.room_id, args.data_room.resolve())

        def show(event: object) -> None:
            data = getattr(event, "data", None)
            label = getattr(data, "track", None) or type(data).__name__
            print(f"[{event.type}] {label}", file=sys.stderr)

        result = await run_ontology_workflow(
            BuildRequest(args.room_id, str(args.data_room)), {**azure_options(), "mapping_model": mapping_model()}, on_event=show
        )
        print(json.dumps({"snapshot_id": result.snapshot_id, "status": result.status, "counts": result.counts}, indent=2))
        return
    if args.command == "publish-snapshot":
        from .ontology.pipeline import publish as publish_snapshot

        print(json.dumps(publish_snapshot(args.room_id, reviewer=args.reviewer, reason=args.reason, force=args.force), indent=2))
        return
    if args.command == "ingest":
        from .azure_services import azure_options
        from .ingest.run import ingest

        _, summary = await ingest(args.room_id, args.data_room, **azure_options())
        print(json.dumps(summary, indent=2))
        return
    if args.command == "catalog":
        _catalog(args)
        return
    if args.command == "doctor":
        checks = await run_doctor(args.data_room)
        print(format_checks(checks))
        if any(check.status == "FAIL" for check in checks):
            sys.exit(1)
        return
    from .ontology.store import Snapshot
    from .service.chat import ask

    answer = await ask(Snapshot(args.room_id), args.question)
    print(answer["answer"])
    for citation in answer["citations"]:
        print(f"  - {citation['label']}")
    print(f"[{answer['mode']}; {', '.join(o['operation'] for o in answer['operations'])}; {answer['seconds']}s]", file=sys.stderr)


def _catalog(args: argparse.Namespace) -> None:
    from .ontology.catalog import export_catalog, load_aliases, load_catalog, load_rules

    catalog = load_catalog()
    rules = load_rules()
    aliases = load_aliases()
    print(
        f"catalog {catalog.catalog_version}: {len(catalog.entity_types)} entity types, "
        f"{len(catalog.relationship_types)} relationship types, {len(catalog.measures)} measures, "
        f"{len(rules.rules)} rules, {len(aliases)} alias tables"
    )
    if args.action == "export":
        for path in export_catalog(args.out):
            print(path)


def main() -> None:
    load_dotenv()
    asyncio.run(_run(parser().parse_args()))


if __name__ == "__main__":
    main()
