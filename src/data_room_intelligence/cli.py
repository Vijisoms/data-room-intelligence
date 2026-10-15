from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .agent import create_qa_agent
from .models import PipelineRequest
from .workflow import run_workflow


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="data-room-intel")
    commands = root.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Build the canonical model and report")
    build.add_argument("data_room", type=Path)
    build.add_argument("--output", type=Path, default=Path("output"))
    build.add_argument("--asset-name", default="Lone Star Basin")
    ask = commands.add_parser("ask", help="Ask the cited Q&A agent")
    ask.add_argument("question")
    ask.add_argument("--output", type=Path, default=Path("output"))
    return root


async def _run(args: argparse.Namespace) -> None:
    if args.command == "build":
        result = await run_workflow(
            PipelineRequest(
                data_room=str(args.data_room),
                output_dir=str(args.output),
                asset_name=args.asset_name,
            )
        )
        print(result.model_dump_json(indent=2))
        return
    agent = create_qa_agent(args.output.resolve())
    response = await agent.run(args.question)
    print(response)


def main() -> None:
    asyncio.run(_run(parser().parse_args()))


if __name__ == "__main__":
    main()

