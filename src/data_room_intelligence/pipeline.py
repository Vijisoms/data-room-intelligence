from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .analytics import calculate_metrics
from .discovery import discover
from .models import CanonicalModel, PipelineRequest, PipelineResult
from .parsers import (
    parse_basis,
    parse_combocurve,
    parse_gis,
    parse_los,
    parse_pdfs,
    parse_unit_details,
)
from .reconcile import reconcile
from .reporting import write_outputs


def run_pipeline(request: PipelineRequest) -> PipelineResult:
    root = Path(request.data_room).resolve()
    output_dir = Path(request.output_dir).resolve()
    files = discover(root)

    def one(kind: str) -> Path:
        matches = [Path(record.path) for record in files if record.kind == kind]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one {kind} file, found {len(matches)}")
        return matches[0]

    unit_file = one("excel_units")
    combo_file = one("excel_combocurve")
    basis_file = one("excel_basis")
    los_file = one("excel_los")
    gis_unit_candidates = [
        Path(record.path)
        for record in files
        if record.kind == "gis_units" and "Maps_2026.09.09" in record.path
    ]
    if len(gis_unit_candidates) != 1:
        raise ValueError(f"Expected one September GIS unit layer, found {len(gis_unit_candidates)}")
    gis_unit_file = gis_unit_candidates[0]
    gis_lease_file = one("gis_leasehold")
    gis_pdp_file = one("gis_pdp")
    pdf_files = [Path(record.path) for record in files if record.kind == "pdf"]

    units, unit_metrics = parse_unit_details(unit_file)
    wells, cash_flow, combo_metrics = parse_combocurve(combo_file)
    spatial_links, gis_metrics = parse_gis(gis_unit_file, gis_lease_file, gis_pdp_file)
    model = CanonicalModel(
        asset_name=request.asset_name,
        generated_at=datetime.now(timezone.utc),
        data_room=str(root),
        files=files,
        units=units,
        wells=wells,
        production=parse_los(los_file),
        metrics=unit_metrics + combo_metrics + gis_metrics,
        findings=[],
        pdf_facts=parse_pdfs(pdf_files),
        pricing=parse_basis(basis_file),
        cash_flow=cash_flow,
    )
    reconcile(model, spatial_links)
    calculate_metrics(model)
    return write_outputs(
        model,
        output_dir,
        spatial_links,
        unit_metrics=unit_metrics,
        combo_metrics=combo_metrics,
        gis_metrics=gis_metrics,
    )
