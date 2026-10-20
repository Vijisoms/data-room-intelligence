"""Chat: an Agent Framework agent whose tools are the named operations; numbers in answers are verified."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Annotated, Any

from pydantic import Field

from ..config import offline
from ..ontology.store import Snapshot
from . import operations as ops

INSTRUCTIONS = (
    "You answer questions about an upstream oil and gas acquisition data room. "
    "Always call exactly one tool (two only if the question clearly needs both) and answer only from its result. "
    "Never compute, estimate or invent numbers: copy numbers exactly as they appear in the tool result. "
    "Keep answers under 110 words, plain sentences, no tables. Mention open conflicts that affect the answer. "
    "If no tool fits, say which questions you can answer."
)
NUMBER = re.compile(r"\d[\d,]*\.?\d*")


def _tools(snap: Snapshot, calls: list[dict[str, Any]]) -> list[Any]:
    from agent_framework import tool

    def record(result: dict[str, Any]) -> str:
        calls.append(result)
        return json.dumps({k: result[k] for k in ("operation", "summary", "data", "citations")}, default=str)

    @tool(name="room_overview", description=ops.OPERATIONS["room_overview"])
    def room_overview() -> str:
        return record(ops.room_overview(snap))

    @tool(name="zone_summary", description=ops.OPERATIONS["zone_summary"])
    def zone_summary(zone: Annotated[str, Field(description="Bench code (WCA, MSS, ...) or name (Wolfcamp A)")]) -> str:
        return record(ops.zone_summary(snap, zone))

    @tool(name="unit_profile", description=ops.OPERATIONS["unit_profile"])
    def unit_profile(unit: Annotated[str, Field(description="Unit name, e.g. GOLDEN CROSSING WEST")]) -> str:
        return record(ops.unit_profile(snap, unit))

    @tool(name="well_profile", description=ops.OPERATIONS["well_profile"])
    def well_profile(well: Annotated[str, Field(description="API number, well name or INPT ID")]) -> str:
        return record(ops.well_profile(snap, well))

    @tool(name="locations", description=ops.OPERATIONS["locations"])
    def locations(
        zone: Annotated[str | None, Field(description="Bench code or name")] = None,
        status: Annotated[str | None, Field(description="PRODUCING, UNDEVELOPED, DUC, DRILLING or PERMIT")] = None,
        unit: Annotated[str | None, Field(description="Unit name")] = None,
    ) -> str:
        return record(ops.locations(snap, zone, status, unit))

    @tool(name="conflicts", description=ops.OPERATIONS["conflicts"])
    def conflicts(
        rule: Annotated[str | None, Field(description="Rule code such as VALUE_FIELD_CONFLICT")] = None,
        entity: Annotated[str | None, Field(description="Entity name or ID to scope the issues")] = None,
    ) -> str:
        return record(ops.conflicts(snap, rule, entity))

    @tool(name="claim_check", description=ops.OPERATIONS["claim_check"])
    def claim_check(document: Annotated[str | None, Field(description="Document name fragment, e.g. overview")] = None) -> str:
        return record(ops.claim_check(snap, document))

    @tool(name="gap_report", description=ops.OPERATIONS["gap_report"])
    def gap_report() -> str:
        return record(ops.gap_report(snap))

    @tool(name="lineage", description=ops.OPERATIONS["lineage"])
    def lineage(entity: Annotated[str, Field(description="Entity name or ID")]) -> str:
        return record(ops.lineage(snap, entity))

    return [room_overview, zone_summary, unit_profile, well_profile, locations, conflicts, claim_check, gap_report, lineage]


def route_offline(snap: Snapshot, question: str, scope: str | None = None) -> dict[str, Any]:
    """Keyword routing used without a model; same operations, template answer."""
    text = question.lower()
    zone = next((code for code, name in ops.BENCH_NAMES.items() if name.lower() in text), None) or next((z for z in ops.ZONES if re.search(rf"\b{re.escape(z.lower())}\b", text)), None)
    if zone and any(word in text for word in ("acre", "pv", "location", "value", "summar", "zone", "bench")):
        return ops.zone_summary(snap, zone)
    if any(word in text for word in ("chart", "deck", "claim", "pdf", "slide")):
        return ops.claim_check(snap)
    if "gap" in text or "missing" in text or "crosswalk" in text:
        return ops.gap_report(snap)
    if any(word in text for word in ("conflict", "issue", "block")) and not any(word in text for word in ("tell me about", "summarize", "profile")):
        return ops.conflicts(snap, rule="VALUE_FIELD_CONFLICT" if "pv" in text else None)
    if any(word in text for word in ("overview", "room", "how many")):
        return ops.room_overview(snap)
    target = re.sub(r"^(tell me about|summari[sz]e( unit)?|show( me)?|what about|profile( of)?|where does .* come from\??)\s+", "", question.strip(), flags=re.I).rstrip("?.! ")
    if "lineage" in text or "come from" in text or "source" in text:
        return ops.lineage(snap, scope or target)
    node = ops.resolve_entity(snap, target) or _mentioned_entity(snap, text) or (snap.nodes.get(scope) if scope else None)
    if node and node["type"] == "Unit":
        return ops.unit_profile(snap, node["id"])
    if node and node["type"] in {"Well", "EconomicLocation"}:
        return ops.well_profile(snap, node["id"])
    if node:
        return ops.lineage(snap, node["id"])
    return ops.result("none", {}, {}, "I answer from named operations: room overview, zone summary, unit or well profile, locations, conflicts, claim check, gap report and lineage. Try a unit, well, API number or bench such as Wolfcamp A.", [])


def _mentioned_entity(snap: Snapshot, text: str) -> dict[str, Any] | None:
    """The well, location or unit whose name (or API number) appears anywhere in the question; the longest match wins."""
    digits = re.sub(r"\D", "", text)
    for length in (14, 10):
        for match in re.finditer(rf"\d{{{length}}}", digits):
            node = snap.nodes.get(f"well:{match.group(0).ljust(14, '0')}")
            if node:
                return node
    best, best_length = None, 0
    for node in snap.nodes.values():
        if node["type"] not in {"Well", "EconomicLocation", "Unit"}:
            continue
        label = node["label"].lower()
        if len(label) >= 5 and len(label) > best_length and re.search(rf"(?<![a-z0-9]){re.escape(label)}(?![a-z0-9])", text):
            best, best_length = node, len(label)
    return best


def _verified(answer: str, results: list[dict[str, Any]]) -> bool:
    """Every number in the model's answer must appear in a tool result (ignoring formatting)."""
    haystack = json.dumps([r["data"] for r in results] + [r["summary"] for r in results], default=str).replace(",", "")
    for token in NUMBER.findall(answer):
        plain = token.replace(",", "").rstrip(".")
        if not plain or plain in {"10", "14"}:
            continue
        if plain not in haystack:
            whole = plain.split(".")[0]
            if not any(candidate.startswith(whole) for candidate in re.findall(r"\d+\.?\d*", haystack)):
                return False
    return True


async def ask(snap: Snapshot, question: str, scope: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    endpoint, model = os.environ.get("FOUNDRY_PROJECT_ENDPOINT"), os.environ.get("FOUNDRY_MODEL")
    calls: list[dict[str, Any]] = []
    answer, mode = None, "offline router"
    if not offline() and endpoint and model:
        try:
            from agent_framework import Agent
            from agent_framework.foundry import FoundryChatClient

            from ..credentials import azure_credential

            agent = Agent(client=FoundryChatClient(project_endpoint=endpoint, model=model, credential=azure_credential()), name="DataRoomCopilot", instructions=INSTRUCTIONS, tools=_tools(snap, calls))
            hint = f"\n(The user is looking at {snap.nodes[scope]['type']} {snap.nodes[scope]['label']}, id {scope}.)" if scope and scope in snap.nodes else ""
            response = await agent.run(question + hint)
            answer, mode = (response.text or "").strip(), f"{model} with named operations"
        except Exception as error:  # noqa: BLE001 - degrade to the offline router
            answer, mode = None, f"offline router (model unavailable: {type(error).__name__})"
    if not calls:
        calls.append(route_offline(snap, question, scope))
        answer = None
    if answer and not _verified(answer, calls):
        answer, mode = None, f"{mode}; model text replaced because it contained a number not in the operation result"
    primary = calls[0]
    return {
        "question": question,
        "answer": answer or primary["summary"],
        "mode": mode,
        "operations": [{"operation": c["operation"], "args": c["args"]} for c in calls],
        "results": [{"operation": c["operation"], "data": c["data"], "summary": c["summary"]} for c in calls],
        "citations": [cite for c in calls for cite in c["citations"]][:8],
        "actions": [action for c in calls for action in c["actions"]][:4],
        "seconds": round(time.perf_counter() - started, 1),
    }
