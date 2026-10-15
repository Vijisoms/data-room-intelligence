from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ..config import slug
from ..contracts import Manifest, ManifestEntry
from ..discovery import infer_as_of

GIS_SIDECARS = {".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix"}
ROLES = [
    (r"unit details", "unit_details", "unit-details"),
    (r"combocurve", "economics_oneline", "combocurve"),
    (r"\blos\b", "lease_operating_statement", "los"),
    (r"basis", "basis_report", "basis"),
    (r"asset overview", "asset_overview_deck", "asset-overview"),
    (r"development model", "development_model_deck", "development-model"),
    (r"pdp", "gis_pdp_laterals", "gis-pdp"),
    (r"leasehold", "gis_leasehold", "gis-leasehold"),
    (r"pf units", "gis_units", "gis-units-pf"),
    (r"units", "gis_units_ownership", "gis-units"),
]


def file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return "excel"
    if suffix in {".csv", ".txt", ".tsv"}:
        return "csv"
    if suffix == ".shp":
        return "gis_layer"
    if suffix in GIS_SIDECARS:
        return "gis_sidecar"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".pptx", ".ppt"}:
        return "presentation"
    return "other"


def guess_role(path: Path, kind: str) -> tuple[str | None, float | None, str]:
    name = path.name.lower().replace("_", " ")
    is_gis = kind in {"gis_layer", "gis_sidecar"}
    for pattern, role, file_id in ROLES:
        if is_gis != file_id.startswith("gis"):
            continue
        if re.search(pattern, name):
            return role, 0.9, file_id
    return None, None, slug(path.stem)


def protection(path: Path, kind: str) -> str:
    if kind != "excel":
        return "none"
    head = path.read_bytes()[:8]
    if head.startswith(b"\xd0\xcf\x11\xe0") and path.suffix.lower() != ".xls":
        return "rights_management"
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as archive:
                archive.getinfo("[Content_Types].xml")
        except (KeyError, zipfile.BadZipFile):
            return "unknown"
    return "none"


def build_manifest(
    room_id: str, sources: list[tuple[Path, Path]], created_at: datetime | None = None
) -> Manifest:
    """sources: (root, file) pairs; paths are recorded relative to their root."""
    entries: list[ManifestEntry] = []
    skipped: list[str] = []
    used_ids: set[str] = set()
    for root, path in sorted(sources, key=lambda item: item[1].relative_to(item[0]).as_posix()):
        relative = path.relative_to(root).as_posix()
        if any(part.startswith((".", "~$")) for part in Path(relative).parts):
            skipped.append(relative)
            continue
        kind = file_kind(path)
        role, confidence, file_id = guess_role(path, kind)
        if kind == "gis_sidecar":
            file_id = f"{file_id}-{path.suffix.lstrip('.')}"
        base, counter = file_id, 2
        while file_id in used_ids:
            file_id, counter = f"{base}-{counter}", counter + 1
        used_ids.add(file_id)
        entries.append(
            ManifestEntry(
                path=relative,
                file_id=file_id,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                size_bytes=path.stat().st_size,
                kind=kind,
                role=role,
                role_confidence=confidence,
                bundle=path.stem if kind in {"gis_layer", "gis_sidecar"} else None,
                protection=protection(path, kind),
                as_of=infer_as_of(path),
            )
        )
    digest = hashlib.sha256("".join(f"{e.path}:{e.sha256}\n" for e in entries).encode()).hexdigest()
    return Manifest(
        room_id=room_id,
        snapshot_id=f"m-{digest[:12]}",
        created_at=created_at or datetime.now(timezone.utc),
        files=entries,
        skipped=skipped,
    )


def room_sources(room_dir: Path, incoming: Path | None = None) -> list[tuple[Path, Path]]:
    sources = [(room_dir, path) for path in room_dir.rglob("*") if path.is_file()]
    if incoming and incoming.is_dir():
        sources += [(incoming.parent, path) for path in incoming.rglob("*") if path.is_file()]
    return sources


def copy_bronze(manifest: Manifest, sources: list[tuple[Path, Path]], bronze: Path) -> None:
    """Byte-identical copies of the originals, so later stages never read the live room."""
    by_path = {path.relative_to(root).as_posix(): path for root, path in sources}
    for entry in manifest.files:
        target = bronze / "originals" / entry.path
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == entry.sha256:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(by_path[entry.path], target)
    (bronze / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
