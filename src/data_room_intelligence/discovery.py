from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .models import FileRecord

DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2})[._-]?(\d{2})[._-]?(\d{2})(?!\d)")


def infer_as_of(path: Path) -> str | None:
    match = DATE_PATTERN.search(path.name)
    if not match:
        return None
    year, month, day = match.groups()
    try:
        return datetime(int(year), int(month), int(day)).date().isoformat()
    except ValueError:
        return None


def classify(path: Path) -> str:
    name = path.name.lower()
    if path.suffix.lower() == ".shp":
        if "pdp" in name:
            return "gis_pdp"
        if "leasehold" in name:
            return "gis_leasehold"
        return "gis_units"
    if path.suffix.lower() == ".pdf":
        return "pdf"
    if path.suffix.lower() in {".xlsx", ".xls"}:
        if "combocurve" in name:
            return "excel_combocurve"
        if "unit details" in name:
            return "excel_units"
        if "basis" in name:
            return "excel_basis"
        if "los" in name:
            return "excel_los"
        return "excel"
    if path.suffix.lower() == ".pptx":
        return "briefing"
    return "other"


def discover(data_room: Path) -> list[FileRecord]:
    """List data-room files with room-relative POSIX paths; skip hidden and Office lock files."""
    root = data_room.resolve()
    records: list[FileRecord] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part.startswith((".", "~$")) for part in relative.parts):
            continue
        stat = path.stat()
        records.append(
            FileRecord(
                path=relative.as_posix(),
                kind=classify(path),
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime),
                as_of=infer_as_of(path),
            )
        )
    return records

