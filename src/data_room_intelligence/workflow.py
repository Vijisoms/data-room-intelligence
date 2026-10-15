from __future__ import annotations

from agent_framework import WorkflowBuilder, WorkflowContext, executor

from .models import PipelineRequest, PipelineResult
from .pipeline import run_pipeline


@executor(id="ingest_normalize_reconcile_analyze_report")
async def build_data_room(
    request: PipelineRequest, ctx: WorkflowContext[PipelineResult, PipelineResult]
) -> None:
    result = run_pipeline(request)
    result.assert_persistent()
    await ctx.yield_output(result)


def create_workflow():
    return WorkflowBuilder(
        start_executor=build_data_room,
        output_from=[build_data_room],
    ).build()


async def run_workflow(request: PipelineRequest) -> PipelineResult:
    events = await create_workflow().run(request)
    outputs = events.get_outputs()
    if len(outputs) != 1 or not isinstance(outputs[0], PipelineResult):
        raise RuntimeError(f"Expected one PipelineResult output, received {outputs!r}")
    return outputs[0]

