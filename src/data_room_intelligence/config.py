from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def slug(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")


def data_root() -> Path:
    return Path(os.environ.get("DRI_DATA_ROOT", REPO_ROOT / ".dri-data")).resolve()


def offline() -> bool:
    return os.environ.get("DRI_OFFLINE", "").strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class RoomPaths:
    room_id: str

    @property
    def root(self) -> Path:
        return data_root() / "rooms" / self.room_id

    @property
    def incoming(self) -> Path:
        """Files added after the original room (uploads); ingested with the room."""
        return self.root / "incoming"

    @property
    def reviews(self) -> Path:
        return self.root / "reviews"

    @property
    def mappings(self) -> Path:
        return self.root / "mappings"

    @property
    def catalog(self) -> Path:
        """Project model extension: extension.yaml (current state), changes.jsonl (append-only), proposals/."""
        return self.root / "catalog"

    @property
    def source(self) -> Path:
        """Original files of a project created in the app (projects built from a repository folder leave it empty)."""
        return self.root / "source"

    @property
    def record(self) -> Path:
        return self.root / "project.json"

    def snapshot(self, snapshot_id: str) -> Path:
        return self.root / "snapshots" / snapshot_id

    def bronze(self, snapshot_id: str) -> Path:
        return self.snapshot(snapshot_id) / "bronze"

    def silver(self, snapshot_id: str) -> Path:
        return self.snapshot(snapshot_id) / "silver"

    def gold(self, snapshot_id: str) -> Path:
        return self.snapshot(snapshot_id) / "gold"

    @property
    def latest_pointer(self) -> Path:
        return self.root / "latest.json"


def cache_dirs() -> list[Path]:
    """Writable cache first, then the read-only seed cache committed with the sample room."""
    return [data_root() / "cache", REPO_ROOT / "data" / "extraction-cache"]
