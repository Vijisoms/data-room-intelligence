from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from .agent import create_qa_agent
from .artifacts import BlobArtifactPublisher
from .models import PipelineRequest
from .workflow import run_workflow


def _add_publish_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--account-url")
    command.add_argument("--container")
    command.add_argument("--asset-id", default="lone-star-basin")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="data-room-intel")
    commands = root.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Build the canonical model and report")
    build.add_argument("data_room", type=Path)
    build.add_argument("--output", type=Path, default=Path("output"))
    build.add_argument("--asset-name", default="Lone Star Basin")
    build.add_argument("--publish", action="store_true")
    _add_publish_arguments(build)
    publish = commands.add_parser("publish", help="Publish generated outputs to Blob Storage")
    publish.add_argument("output", type=Path, nargs="?", default=Path("output"))
    _add_publish_arguments(publish)
    ask = commands.add_parser("ask", help="Ask the cited Q&A agent")
    ask.add_argument("question")
    ask.add_argument("--output", type=Path, default=Path("output"))
    return root


async def _run(args: argparse.Namespace) -> None:
    load_dotenv()
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
        credential=DefaultAzureCredential(),
    )
    return publisher.publish(output_dir, asset_id=args.asset_id)


def main() -> None:
    asyncio.run(_run(parser().parse_args()))


if __name__ == "__main__":
    main()
