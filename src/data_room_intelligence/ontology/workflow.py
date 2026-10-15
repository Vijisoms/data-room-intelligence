"""Agent Framework workflow: discover -> (GIS | tables | PDF in parallel) -> collect -> build -> review gate -> publish."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_framework import Executor, FileCheckpointStorage, WorkflowBuilder, WorkflowContext, handler, response_handler
from typing_extensions import Never

from ..config import data_root
from ..ingest.run import IngestContext, discover, finalize_silver, run_gis, run_pdf, run_tabular
from ..contracts import Manifest
from .pipeline import build_gold, publish
from .store import Snapshot


@dataclass
class BuildRequest:
    room_id: str = "lone-star-basin"
    room_dir: str = "data/sample-room"
    require_review: bool = True


@dataclass
class Stage:
    room_id: str
    snapshot_id: str
    room_dir: str
    require_review: bool = True


@dataclass
class TrackResult:
    track: str
    summary: dict[str, Any]
    stage: Stage


@dataclass
class ReviewRequest:
    room_id: str
    snapshot_id: str
    open_blocking: int
    rules: list[str]
    message: str


@dataclass
class ReviewResponse:
    action: str = "hold"
    reviewer: str = ""
    reason: str = ""


@dataclass
class BuildResult:
    room_id: str
    snapshot_id: str
    status: str
    counts: dict[str, Any] = field(default_factory=dict)


def _context(stage: Stage) -> IngestContext:
    from ..config import RoomPaths

    paths = RoomPaths(stage.room_id)
    manifest = Manifest.model_validate_json((paths.bronze(stage.snapshot_id) / "manifest.json").read_text("utf-8"))
    return IngestContext(stage.room_id, stage.snapshot_id, manifest, paths.bronze(stage.snapshot_id), paths.silver(stage.snapshot_id))


class Discover(Executor):
    @handler
    async def run(self, request: BuildRequest, ctx: WorkflowContext[Stage]) -> None:
        ingest_ctx = discover(request.room_id, Path(request.room_dir))
        await ctx.send_message(Stage(request.room_id, ingest_ctx.snapshot_id, request.room_dir, request.require_review))


class GisTrack(Executor):
    @handler
    async def run(self, stage: Stage, ctx: WorkflowContext[TrackResult, TrackResult]) -> None:
        result = TrackResult("gis", run_gis(_context(stage)), stage)
        await ctx.yield_output(result)
        await ctx.send_message(result)


class TabularTrack(Executor):
    @handler
    async def run(self, stage: Stage, ctx: WorkflowContext[TrackResult, TrackResult]) -> None:
        result = TrackResult("tabular", run_tabular(_context(stage)), stage)
        await ctx.yield_output(result)
        await ctx.send_message(result)


class PdfTrack(Executor):
    def __init__(self, options: dict[str, Any], id: str = "pdf") -> None:
        super().__init__(id=id)
        self.options = {k: v for k, v in options.items() if k in {"endpoint", "credential", "vision_model", "client_factory"}}

    @handler
    async def run(self, stage: Stage, ctx: WorkflowContext[TrackResult, TrackResult]) -> None:
        result = TrackResult("pdf", await run_pdf(_context(stage), **self.options), stage)
        await ctx.yield_output(result)
        await ctx.send_message(result)


class BuildOntology(Executor):
    """Collects the three tracks, builds Gold, then pauses for review when blocking issues are open."""

    def __init__(self, options: dict[str, Any], id: str = "build") -> None:
        super().__init__(id=id)
        self.options = options

    @handler
    async def run(self, results: list[TrackResult], ctx: WorkflowContext[Never, BuildResult]) -> None:
        stage = results[0].stage
        ingest_ctx = _context(stage)
        finalize_silver(ingest_ctx, [result.summary for result in results])
        snapshot = await build_gold(ingest_ctx, self.options.get("client_factory"), self.options.get("mapping_model"))
        open_blocking = [i for i in Snapshot(stage.room_id, stage.snapshot_id).issues if i["severity"] == "blocking" and i["status"] == "open"]
        if open_blocking and stage.require_review:
            await ctx.request_info(
                ReviewRequest(stage.room_id, stage.snapshot_id, len(open_blocking), sorted({i["rule"] for i in open_blocking}),
                              "Blocking issues are open. Respond 'publish' (with reviewer and reason) or 'hold' to keep the snapshot in review."),
                ReviewResponse,
            )
            return
        await ctx.yield_output(BuildResult(stage.room_id, stage.snapshot_id, snapshot["status"], snapshot["counts"]))

    @response_handler
    async def on_review(self, original: ReviewRequest, response: ReviewResponse, ctx: WorkflowContext[Never, BuildResult]) -> None:
        status = "in_review"
        if response.action == "publish":
            outcome = publish(original.room_id, original.snapshot_id, response.reviewer, response.reason, force=True)
            status = "published" if outcome["published"] else status
        await ctx.yield_output(BuildResult(original.room_id, original.snapshot_id, status, {"open_blocking": original.open_blocking, "review": response.action}))


def create_ontology_workflow(options: dict[str, Any] | None = None, checkpoints: bool = True):
    options = options or {}
    discover_ = Discover(id="discover")
    tracks = [GisTrack(id="gis"), TabularTrack(id="tabular"), PdfTrack(options, id="pdf")]
    build_ = BuildOntology(options, id="build")
    storage = None
    if checkpoints:
        allowed = [f"{__name__}:{cls.__qualname__}" for cls in (BuildRequest, Stage, TrackResult, ReviewRequest, ReviewResponse, BuildResult)]
        storage = FileCheckpointStorage(str(data_root() / "checkpoints"), allowed_checkpoint_types=allowed)
    builder = WorkflowBuilder(start_executor=discover_, checkpoint_storage=storage, output_from=[build_], intermediate_output_from=tracks)
    return builder.add_fan_out_edges(discover_, tracks).add_fan_in_edges(tracks, build_).build()
