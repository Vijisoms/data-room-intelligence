from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .agent import create_qa_agent
from .artifacts import BlobArtifactPublisher
from .credentials import azure_credential
from .doctor import format_checks, run_doctor
from .models import PipelineRequest
from .workflow import run_workflow


def _add_publish_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--account-url")
    command.add_argument("--container")
    command.add_argument("--asset-id", default="lone-star-basin")


def parser() -> argparse.ArgumentParser:
    data_room = Path(os.environ.get("DATA_ROOM_PATH", "data/sample-room"))
    output = Path(os.environ.get("DATA_ROOM_OUTPUT", "output"))
    root = argparse.ArgumentParser(prog="data-room-intel")
    commands = root.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Build the canonical model and report")
    build.add_argument("data_room", type=Path, nargs="?", default=data_room)
    build.add_argument("--output", type=Path, default=output)
    build.add_argument("--asset-name", default="Lone Star Basin")
    build.add_argument("--publish", action="store_true")
    _add_publish_arguments(build)
    publish = commands.add_parser("publish", help="Publish generated outputs to Blob Storage")
    publish.add_argument("output", type=Path, nargs="?", default=output)
    _add_publish_arguments(publish)
    ask = commands.add_parser("ask", help="Ask the cited Q&A agent")
    ask.add_argument("question")
    ask.add_argument("--output", type=Path, default=output)
    doctor = commands.add_parser(
        "doctor", help="Check the data room, Azure identity, Foundry models and Document Intelligence"
    )
    doctor.add_argument("--data-room", type=Path, default=data_room)
    catalog = commands.add_parser("catalog", help="Validate the ontology catalog or export review artifacts")
    catalog.add_argument("action", choices=["validate", "export"])
    catalog.add_argument("--out", type=Path, default=Path("docs/catalog"))
    return root


async def _run(args: argparse.Namespace) -> None:
    if args.command == "catalog":
        _catalog(args)
        return
    if args.command == "doctor":
        checks = await run_doctor(args.data_room)
        print(format_checks(checks))
        if any(check.status == "FAIL" for check in checks):
            sys.exit(1)
        return
    if args.command == "build":
        result = await run_workflow(
            PipelineRequest(
                data_room=str(args.data_room),
                output_dir=str(args.output),
                asset_name=args.asset_name,
            )
        )
        response: dict[str, object] = {"pipeline": result.model_dump(mode="json")}
        if args.publish:
            response["publish"] = _publish(args.output, args)
        print(json.dumps(response, indent=2))
        return
    if args.command == "publish":
        print(json.dumps(_publish(args.output, args), indent=2))
        return
    agent = create_qa_agent(args.output.resolve())
    response = await agent.run(args.question)
    print(response)


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


def _publish(output_dir: Path, args: argparse.Namespace) -> dict[str, object]:
    account_url = args.account_url or os.environ.get("DATA_ROOM_STORAGE_ACCOUNT_URL")
    container = args.container or os.environ.get("DATA_ROOM_STORAGE_CONTAINER")
    if not account_url or not container:
        raise RuntimeError(
            "Set DATA_ROOM_STORAGE_ACCOUNT_URL and DATA_ROOM_STORAGE_CONTAINER, "
            "or pass --account-url and --container."
        )
    publisher = BlobArtifactPublisher(
        account_url=account_url,
        container=container,
        credential=azure_credential(),
    )
    return publisher.publish(output_dir, asset_id=args.asset_id)


def main() -> None:
    load_dotenv()
    asyncio.run(_run(parser().parse_args()))


if __name__ == "__main__":
    main()
