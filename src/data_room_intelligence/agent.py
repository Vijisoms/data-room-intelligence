from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from azure.core.credentials import TokenCredential
from dotenv import load_dotenv
from pydantic import Field

from .artifacts import ArtifactReader, BlobArtifactReader, LocalArtifactReader
from .credentials import azure_credential


class CanonicalQueryTools:
    def __init__(self, artifacts: ArtifactReader) -> None:
        self.artifacts = artifacts

    @tool(
        name="get_standard_answers",
        description="Return reconciled standard acquisition answers with deterministic calculations.",
    )
    def get_standard_answers(self) -> str:
        return self.artifacts.read_text("standard-answers.json")

    @tool(
        name="get_qa_findings",
        description="Return cross-source conflicts, data gaps, and reconciliation findings.",
    )
    def get_qa_findings(self) -> str:
        return self.artifacts.read_text("qa-findings.json")

    @tool(
        name="search_metrics",
        description="Search canonical metrics by a case-insensitive metric or dimension term.",
    )
    def search_metrics(
        self,
        query: Annotated[str, Field(description="Metric, zone, or dimension term")],
    ) -> str:
        model = json.loads(self.artifacts.read_text("canonical-model.json"))
        needle = query.casefold()
        matches = [
            metric
            for metric in model["metrics"]
            if needle in json.dumps(metric).casefold()
        ]
        return json.dumps(matches[:100], indent=2)


def create_qa_agent(output_dir: Path) -> Agent:
    return create_qa_agent_from_reader(LocalArtifactReader(output_dir))


def create_blob_qa_agent(
    account_url: str,
    container: str,
    asset_id: str,
    credential: TokenCredential,
) -> Agent:
    return create_qa_agent_from_reader(
        BlobArtifactReader(
            account_url=account_url,
            container=container,
            asset_id=asset_id,
            credential=credential,
        )
    )


def create_qa_agent_from_reader(artifacts: ArtifactReader) -> Agent:
    load_dotenv()
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    model = os.environ.get("FOUNDRY_MODEL")
    if not endpoint or not model:
        raise RuntimeError(
            "Set FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL to enable Agent Framework Q&A."
        )
    tools = CanonicalQueryTools(artifacts)
    return Agent(
        client=FoundryChatClient(
            project_endpoint=endpoint,
            model=model,
            credential=azure_credential(),
        ),
        name="DataRoomIntelligenceAgent",
        instructions=(
            "Answer upstream acquisition questions only from the provided canonical tools. "
            "Never invent a missing value. Distinguish contractual acreage from GIS footprint "
            "area and distinguish unit-schedule locations from ComboCurve locations. Cite source "
            "path and locator fields included in tool results. State material QA warnings."
        ),
        tools=[
            tools.get_standard_answers,
            tools.get_qa_findings,
            tools.search_metrics,
        ],
    )
