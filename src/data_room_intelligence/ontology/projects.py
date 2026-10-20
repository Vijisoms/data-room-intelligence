"""Projects: one data room per project, each with its own files, snapshots, decisions and model extension.

Every project starts from the governed base model (`ontology/catalog.yaml`). A project may extend it
(see `catalog.py`); the extension can be copied from another project when a new one is created.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import REPO_ROOT, RoomPaths, data_root, slug

DEFAULT_ROOM_ID = os.environ.get("DATA_ROOM_ASSET_ID", "lone-star-basin")
DEFAULT_ROOM_DIR = os.environ.get("DATA_ROOM_PATH", "data/sample-room")
TEMPLATES = {"base": "Upstream deal template (governed base model)", "copy": "Base model plus another project's extensions"}


def room_dir(record: dict[str, Any]) -> Path:
    """Folder holding the project's original files; relative paths are repository-relative."""
    path = Path(record["room_dir"])
    return path if path.is_absolute() else REPO_ROOT / path


def ensure_default_project() -> dict[str, Any]:
    """The sample room configured by DATA_ROOM_ASSET_ID / DATA_ROOM_PATH is always registered."""
    path = RoomPaths(DEFAULT_ROOM_ID).record
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    return _write(
        {
            "room_id": DEFAULT_ROOM_ID,
            "name": "Lone Star Basin" if DEFAULT_ROOM_ID == "lone-star-basin" else DEFAULT_ROOM_ID,
            "description": "Sample data room (synthetic). Registered from DATA_ROOM_PATH.",
            "room_dir": DEFAULT_ROOM_DIR,
            "template": "base",
            "copied_from": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def get_project(room_id: str) -> dict[str, Any] | None:
    if room_id == DEFAULT_ROOM_ID:
        return ensure_default_project()
    path = RoomPaths(room_id).record
    if path.exists():
        return json.loads(path.read_text("utf-8"))
    # A room folder created by the CLI without a record still counts as a project.
    if RoomPaths(room_id).root.is_dir():
        return {"room_id": room_id, "name": room_id, "description": "", "room_dir": str(RoomPaths(room_id).source), "template": "base", "copied_from": None, "created_at": None}
    return None


def list_projects() -> list[dict[str, Any]]:
    ensure_default_project()
    rooms = data_root() / "rooms"
    records = [get_project(folder.name) for folder in sorted(rooms.glob("*")) if folder.is_dir()] if rooms.is_dir() else []
    return [r for r in records if r]


def create_project(name: str, description: str = "", template: str = "base", copied_from: str | None = None) -> dict[str, Any]:
    room_id = slug(name)
    if not room_id:
        raise ValueError("the project needs a name")
    if get_project(room_id) is not None:
        raise ValueError(f"a project with ID {room_id} already exists")
    if template not in TEMPLATES:
        raise ValueError(f"unknown template {template}")
    if template == "copy":
        source = get_project(copied_from or "")
        if source is None:
            raise ValueError("choose a project to copy the model from")
    paths = RoomPaths(room_id)
    paths.source.mkdir(parents=True, exist_ok=True)
    paths.catalog.mkdir(parents=True, exist_ok=True)
    if template == "copy":
        from .catalog import copy_extension

        copy_extension(copied_from or "", room_id)
    return _write(
        {
            "room_id": room_id,
            "name": name.strip(),
            "description": description.strip(),
            "room_dir": str(paths.source),
            "template": template,
            "copied_from": copied_from if template == "copy" else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def ensure_project(room_id: str, room_folder: str | Path, name: str | None = None) -> dict[str, Any]:
    """Register a room built from the command line (`snapshot <folder> --room-id X`) so the app can open and rebuild it."""
    record = get_project(room_id)
    if record is not None and RoomPaths(room_id).record.exists():
        return record
    return _write(
        {
            "room_id": room_id,
            "name": name or room_id.replace("-", " ").title(),
            "description": f"Built from {room_folder} with the command line.",
            "room_dir": str(room_folder),
            "template": "base",
            "copied_from": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def delete_project(room_id: str) -> None:
    if room_id == DEFAULT_ROOM_ID:
        raise ValueError("the sample project cannot be deleted")
    shutil.rmtree(RoomPaths(room_id).root, ignore_errors=True)


def _write(record: dict[str, Any]) -> dict[str, Any]:
    path = RoomPaths(record["room_id"]).record
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record
