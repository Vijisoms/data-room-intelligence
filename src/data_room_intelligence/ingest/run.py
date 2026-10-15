from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ..config import RoomPaths
from ..contracts import DatasetSchema, Manifest
from ..ontology.catalog import catalog_fingerprint
from .families import extract_workbook, load_grids
from .gis import feature_rows, geojson, layer_schema, read_layer, spatial_candidates
from .manifest import build_manifest, copy_bronze, room_sources
from .pdf import analyze_document
from .tabular import profile, staged_rows

PIPELINE_VERSION = "pipeline-0.1"


@dataclass
class IngestContext:
    room_id: str
    snapshot_id: str
    manifest: Manifest
    bronze: Path
    silver: Path

    def original(self, relative: str) -> Path:
        return self.bronze / "originals" / relative


def discover(room_id: str, room_dir: Path) -> IngestContext:
    paths = RoomPaths(room_id)
    sources = room_sources(room_dir, paths.incoming)
    manifest = build_manifest(room_id, sources)
    seed = f"{manifest.snapshot_id}|{catalog_fingerprint()}|{PIPELINE_VERSION}"
    snapshot_id = "s-" + hashlib.sha256(seed.encode()).hexdigest()[:12]
    manifest = manifest.model_copy(update={"snapshot_id": snapshot_id})
    copy_bronze(manifest, sources, paths.bronze(snapshot_id))
    silver = paths.silver(snapshot_id)
    silver.mkdir(parents=True, exist_ok=True)
    return IngestContext(room_id, snapshot_id, manifest, paths.bronze(snapshot_id), silver)


def _write_schemas(silver: Path, track: str, schemas: list[DatasetSchema]) -> None:
    folder = silver / "schemas"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{track}.json").write_text(json.dumps([item.model_dump(mode="json") for item in schemas], indent=1), encoding="utf-8")


def run_gis(ctx: IngestContext) -> dict[str, Any]:
    out = ctx.silver / "gis"
    out.mkdir(parents=True, exist_ok=True)
    layers = {}
    for entry in ctx.manifest.files:
        if entry.kind == "gis_layer":
            layers[entry.role or entry.file_id] = read_layer(ctx.original(entry.path), entry.file_id, entry.path)
    rows, schemas = [], []
    for layer in layers.values():
        rows.extend(feature_rows(layer))
        schemas.append(layer_schema(layer))
        (out / f"{layer.file_id}.geojson").write_text(json.dumps(geojson(layer)), encoding="utf-8")
    if rows:
        pq.write_table(pa.Table.from_pylist(rows), out / "features.parquet")
    candidates = []
    if {"gis_units", "gis_pdp_laterals", "gis_leasehold"} <= set(layers):
        candidates = spatial_candidates(layers["gis_units"], layers["gis_pdp_laterals"], layers["gis_leasehold"], layers.get("gis_units_ownership"))
        pq.write_table(pa.Table.from_pylist(candidates), out / "spatial_candidates.parquet")
    _write_schemas(ctx.silver, "gis", schemas)
    kinds = Counter(item["kind"] for item in candidates)
    return {
        "track": "gis",
        "layers": {layer.file_id: len(layer.records) for layer in layers.values()},
        "invalid_geometries": sum(not row["valid"] for row in rows),
        "spatial_candidates": dict(kinds),
        "laterals_crossing_tracts": len({item["source_index"] for item in candidates if item["kind"] == "lateral_crosses_tract"}),
    }


def run_tabular(ctx: IngestContext) -> dict[str, Any]:
    out = ctx.silver / "tabular"
    out.mkdir(parents=True, exist_ok=True)
    values, schemas, tables, sheets = [], [], [], []
    for entry in ctx.manifest.files:
        if entry.kind not in {"excel", "csv"} or entry.protection != "none":
            continue
        grids = load_grids(ctx.original(entry.path))
        for grid in grids:
            filled = sum(value not in (None, "") for row in grid.values for value in row)
            formulas = sum(1 for r in range(1, grid.max_row + 1) for c in range(1, grid.max_col + 1) if grid.formula(r, c))
            uncached = sum(1 for r in range(1, grid.max_row + 1) for c in range(1, grid.max_col + 1) if grid.formula(r, c) and grid.get(r, c) is None)
            sheets.append({"file_id": entry.file_id, "file": entry.path, "sheet": grid.name, "rows": grid.max_row, "columns": grid.max_col, "filled_cells": filled, "formula_cells": formulas, "uncached_formulas": uncached})
        for table in extract_workbook(grids, entry.path, entry.file_id, entry.role):
            schema = profile(table)
            schemas.append(schema)
            values.extend(staged_rows(table))
            tables.append(
                {
                    "dataset_id": table.dataset_id,
                    "file_id": entry.file_id,
                    "file": entry.path,
                    "sheet": table.sheet,
                    "header_rows": table.header_rows,
                    "headers": table.headers,
                    "records": len(table.records),
                    "family": table.context.get("family", "generic"),
                    "context": {k: v for k, v in table.context.items() if k != "family"},
                }
            )
    if values:
        pq.write_table(pa.Table.from_pylist(values), out / "values.parquet")
    (out / "tables.json").write_text(json.dumps(tables, indent=1, default=str), encoding="utf-8")
    (out / "sheets.json").write_text(json.dumps(sheets, indent=1), encoding="utf-8")
    _write_schemas(ctx.silver, "tabular", schemas)
    return {
        "track": "tabular",
        "sheets": len(sheets),
        "tables": len(tables),
        "staged_values": len(values),
        "uncached_formula_values": sum(row["quality"] == "uncached_formula" for row in values),
        "families": dict(Counter(item["family"] for item in tables)),
    }


async def run_pdf(ctx: IngestContext, endpoint: str | None = None, credential: Any = None, vision_model: str | None = None, client_factory: Any = None) -> dict[str, Any]:
    documents = []
    for entry in ctx.manifest.files:
        if entry.kind == "pdf":
            documents.append(
                await analyze_document(
                    ctx.original(entry.path), entry.file_id, entry.path, entry.sha256, ctx.silver / "documents" / entry.file_id,
                    endpoint=endpoint, credential=credential, vision_model=vision_model, client_factory=client_factory,
                )
            )
    return {
        "track": "pdf",
        "documents": len(documents),
        "pages": sum(len(doc["pages"]) for doc in documents),
        "paragraphs": sum(len(doc["paragraphs"]) for doc in documents),
        "figures": sum(len(doc["figures"]) for doc in documents),
        "charts": sum(bool(fig["chart"] and fig["chart"].get("is_chart")) for doc in documents for fig in doc["figures"]),
        "claims": sum(len(doc["claims"]) for doc in documents),
        "sources": sorted({doc["source"] for doc in documents}),
    }


def finalize_silver(ctx: IngestContext, summaries: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "room_id": ctx.room_id,
        "snapshot_id": ctx.snapshot_id,
        "files": len(ctx.manifest.files),
        "skipped": ctx.manifest.skipped,
        "tracks": {item["track"]: item for item in summaries},
    }
    (ctx.silver / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def load_schemas(silver: Path) -> list[DatasetSchema]:
    schemas = []
    for path in sorted((silver / "schemas").glob("*.json")):
        schemas.extend(DatasetSchema.model_validate(item) for item in json.loads(path.read_text("utf-8")))
    return schemas


async def ingest(room_id: str, room_dir: Path, **pdf_options: Any) -> tuple[IngestContext, dict[str, Any]]:
    ctx = discover(room_id, room_dir)
    summaries = [run_gis(ctx), run_tabular(ctx), await run_pdf(ctx, **pdf_options)]
    return ctx, finalize_silver(ctx, summaries)
