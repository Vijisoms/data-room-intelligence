from __future__ import annotations

from agent_framework.devui import serve
from dotenv import load_dotenv

from .ontology.workflow import create_ontology_workflow


def main() -> None:
    load_dotenv()
    serve(entities=[create_ontology_workflow()], port=8088, host="127.0.0.1", auto_open=False, auth_enabled=False)


if __name__ == "__main__":
    main()

