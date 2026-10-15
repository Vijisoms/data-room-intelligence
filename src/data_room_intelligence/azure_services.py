from __future__ import annotations

import os
from typing import Any

from .config import offline
from .credentials import azure_credential


def azure_options() -> dict[str, Any]:
    """Live Azure settings for extraction, or nothing when offline (cached results are still used)."""
    if offline():
        return {}
    credential = azure_credential()
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")

    def client_factory(model: str):
        from agent_framework.foundry import FoundryChatClient

        return FoundryChatClient(project_endpoint=endpoint, model=model, credential=credential)

    return {
        "endpoint": os.environ.get("DOC_INTELLIGENCE_ENDPOINT"),
        "credential": credential,
        "vision_model": os.environ.get("FOUNDRY_VISION_MODEL"),
        "client_factory": client_factory if endpoint else None,
    }
