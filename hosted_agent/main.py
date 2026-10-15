from __future__ import annotations

import json
import os
from time import monotonic
from typing import Annotated

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient
from pydantic import Field


class BlobCanonicalQueryTools:
    def __init__(
        self,
        account_url: str,
        container: str,
        asset_id: str,
        credential: ManagedIdentityCredential,
    ) -> None:
        self.container = BlobServiceClient(
            account_url=account_url,
            credential=credential,
        ).get_container_client(container)
        self.latest_blob = f"assets/{asset_id}/latest.json"
        self._manifest: dict[str, object] | None = None
        self._manifest_loaded_at = 0.0

    def _read(self, artifact: str) -> str:
        now = monotonic()
        if self._manifest is None or now - self._manifest_loaded_at >= 60:
            payload = self.container.download_blob(self.latest_blob).readall()
            manifest = json.loads(payload)
            if not isinstance(manifest, dict):
                raise ValueError(f"{self.latest_blob} must contain a JSON object.")
            self._manifest = manifest
            self._manifest_loaded_at = now
        artifacts = self._manifest.get("artifacts")
        if not isinstance(artifacts, dict) or artifact not in artifacts:
            raise FileNotFoundError(
                f"Artifact {artifact!r} is not present in {self.latest_blob}."
            )
        blob_name = artifacts[artifact]
        if not isinstance(blob_name, str):
            raise ValueError(f"Invalid blob path for artifact {artifact!r}.")
        return self.container.download_blob(blob_name).readall().decode("utf-8")

    @tool(
        name="get_standard_answers",
        description="Return reconciled standard acquisition answers with deterministic calculations.",
        approval_mode="never_require",
    )
    def get_standard_answers(self) -> str:
        return self._read("standard-answers.json")

    @tool(
        name="get_qa_findings",
        description="Return cross-source conflicts, data gaps, and reconciliation findings.",
        approval_mode="never_require",
    )
    def get_qa_findings(self) -> str:
        return self._read("qa-findings.json")

    @tool(
        name="search_metrics",
        description="Search canonical metrics by a case-insensitive metric or dimension term.",
        approval_mode="never_require",
    )
    def search_metrics(
        self,
        query: Annotated[str, Field(description="Metric, zone, or dimension term")],
    ) -> str:
        model = json.loads(self._read("canonical-model.json"))
        needle = query.casefold()
        matches = [
            metric
            for metric in model["metrics"]
            if needle in json.dumps(metric).casefold()
        ]
        return json.dumps(matches[:100], indent=2)


def main() -> None:
    credential = ManagedIdentityCredential()
    tools = BlobCanonicalQueryTools(
        account_url=os.environ["DATA_ROOM_STORAGE_ACCOUNT_URL"],
        container=os.environ["DATA_ROOM_STORAGE_CONTAINER"],
        asset_id=os.environ.get("DATA_ROOM_ASSET_ID", "lone-star-basin"),
        credential=credential,
    )
    agent = Agent(
        client=FoundryChatClient(
            project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
            model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
            credential=credential,
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
        default_options={"store": False},
    )
    ResponsesHostServer(agent).run()


if __name__ == "__main__":
    main()
