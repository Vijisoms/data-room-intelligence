from __future__ import annotations

import os
from pathlib import Path

from agent_framework.devui import serve
from dotenv import load_dotenv

from .agent import create_qa_agent
from .ontology.workflow import create_ontology_workflow
from .workflow import create_workflow


def main() -> None:
    load_dotenv()
    output_dir = Path(os.environ.get("DATA_ROOM_OUTPUT", "output")).resolve()
    if not (output_dir / "canonical-model.json").is_file():
        raise FileNotFoundError(
            f"{output_dir / 'canonical-model.json'} is missing. Run the build command first."
        )
    serve(
        entities=[create_qa_agent(output_dir), create_workflow(), create_ontology_workflow()],
        port=8088,
        host="127.0.0.1",
        auto_open=False,
        auth_enabled=False,
    )


if __name__ == "__main__":
    main()

