"""Run the ontology workflow from the CLI, answering the review gate."""

from __future__ import annotations

from typing import Any

from .workflow import BuildRequest, BuildResult, ReviewRequest, ReviewResponse, create_ontology_workflow


async def run_ontology_workflow(request: BuildRequest, options: dict[str, Any], review: ReviewResponse | None = None, on_event: Any = None) -> BuildResult:
    workflow_options = {k: v for k, v in options.items() if k != "mapping_model"}
    pdf_options = {k: v for k, v in options.items() if k in {"endpoint", "credential", "vision_model", "client_factory"}}
    workflow = create_ontology_workflow({**pdf_options, "client_factory": workflow_options.get("client_factory"), "mapping_model": options.get("mapping_model")})
    result = await workflow.run(request)
    for event in result:
        if on_event and getattr(event, "type", None) in {"output", "intermediate_output", "request_info"}:
            on_event(event)
    requests = [event for event in result if getattr(event, "type", None) == "request_info"]
    if requests:
        response = review or ReviewResponse(action="hold")
        result = await workflow.run(responses={requests[0].request_id: response})
        for event in result:
            if on_event and getattr(event, "type", None) == "output":
                on_event(event)
    outputs = [item for item in result.get_outputs() if isinstance(item, BuildResult)]
    if not outputs:
        raise RuntimeError("workflow finished without a BuildResult")
    return outputs[-1]


__all__ = ["BuildRequest", "BuildResult", "ReviewRequest", "ReviewResponse", "run_ontology_workflow"]
