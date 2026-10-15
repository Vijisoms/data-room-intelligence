from __future__ import annotations

import csv
import json
from pathlib import Path

from .analytics import standard_answers
from .fimu import build_fimu_case
from .models import CanonicalModel, Metric, PipelineResult
from .parsing_docs import render_parsing_guides


def write_outputs(
    model: CanonicalModel,
    output_dir: Path,
    spatial_links: list[dict[str, object]],
    unit_metrics: list[Metric] | None = None,
    combo_metrics: list[Metric] | None = None,
    gis_metrics: list[Metric] | None = None,
) -> PipelineResult:
    unit_metrics = unit_metrics or []
    combo_metrics = combo_metrics or []
    gis_metrics = gis_metrics or []
    output_dir.mkdir(parents=True, exist_ok=True)
    parsed_dir = output_dir / "parsed_json"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "canonical-model.json"
    units_path = parsed_dir / "units.json"
    wells_path = parsed_dir / "wells.json"
    report_path = output_dir / "insight-report.md"
    qa_path = output_dir / "qa-findings.json"
    fimu_path = output_dir / "fimu-case.json"
    answers_path = output_dir / "standard-answers.json"
    links_path = output_dir / "well-unit-links.csv"

    model_path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    units_path.write_text(
        json.dumps(
            {
                "schema_version": model.schema_version,
                "asset_name": model.asset_name,
                "generated_at": model.generated_at.isoformat(),
                "units": [unit.model_dump(mode="json") for unit in model.units],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    wells_path.write_text(
        json.dumps(
            {
                "schema_version": model.schema_version,
                "asset_name": model.asset_name,
                "generated_at": model.generated_at.isoformat(),
                "wells": [well.model_dump(mode="json") for well in model.wells],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    for filename, collection, records in (
        ("cash_flow.json", "cash_flow", model.cash_flow),
        (
            "combo_metrics.json",
            "metrics",
            [metric.model_dump(mode="json") for metric in combo_metrics],
        ),
        ("spatial_links.json", "spatial_links", spatial_links),
        (
            "gis_metrics.json",
            "metrics",
            [metric.model_dump(mode="json") for metric in gis_metrics],
        ),
        (
            "production.json",
            "production",
            [item.model_dump(mode="json") for item in model.production],
        ),
        ("pdf_facts.json", "pdf_facts", model.pdf_facts),
        ("pricing.json", "pricing", model.pricing),
    ):
        (parsed_dir / filename).write_text(
            json.dumps(
                {
                    "schema_version": model.schema_version,
                    "asset_name": model.asset_name,
                    "generated_at": model.generated_at.isoformat(),
                    collection: records,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    for filename, content in render_parsing_guides(
        model, spatial_links, unit_metrics, combo_metrics, gis_metrics
    ).items():
        (parsed_dir / filename).write_text(content, encoding="utf-8")
    answers = standard_answers(model)
    answers_path.write_text(json.dumps(answers, indent=2), encoding="utf-8")
    qa_path.write_text(
        json.dumps([item.model_dump(mode="json") for item in model.findings], indent=2),
        encoding="utf-8",
    )
    fimu_path.write_text(build_fimu_case(model).model_dump_json(indent=2), encoding="utf-8")
    if spatial_links:
        with links_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(spatial_links[0]))
            writer.writeheader()
            writer.writerows(spatial_links)
    report_path.write_text(_render_report(model, answers), encoding="utf-8")
    return PipelineResult(
        model_path=str(model_path.resolve()),
        report_path=str(report_path.resolve()),
        fimu_path=str(fimu_path.resolve()),
        qa_path=str(qa_path.resolve()),
        output_dir=str(output_dir.resolve()),
    )


def _render_report(model: CanonicalModel, answers: dict[str, object]) -> str:
    snapshot = answers["asset_snapshot"]
    wca = answers["worked_example_wca"]
    citations = {
        Path(record.path).name
        for record in model.files
        if record.kind
        in {
            "excel_combocurve",
            "excel_units",
            "excel_basis",
            "excel_los",
            "gis_units",
            "gis_leasehold",
            "gis_pdp",
            "pdf",
        }
    }
    finding_lines = "\n".join(
        f"- **{finding.severity.upper()} — {finding.code}:** {finding.message}"
        for finding in model.findings
    )
    citation_lines = "\n".join(f"- `{name}`" for name in sorted(citations))
    wca_citations = wca["citations"]
    worked_sources = "\n".join(
        f"- **{label}:** "
        + "; ".join(
            f"`{Path(item['path']).name}` — {item.get('locator') or 'file'}"
            for item in source_items
        )
        for label, source_items in wca_citations.items()
    )
    economics = answers["value_and_economics"]
    production = answers["production_and_reserves"]
    return f"""# {model.asset_name} — Data Room Intelligence Report

Generated from the provenance-aware canonical model. All source data is synthetic.

## Executive snapshot

| Metric | Result |
|---|---:|
| Drilling units | {snapshot['units']:,.0f} |
| Contractual gross acres | {snapshot['gross_acres']:,.2f} |
| Economic locations | {snapshot['economic_locations']:,.0f} |
| Producing wells | {snapshot['producing_wells']:,.0f} |
| Average WI | {snapshot['average_wi']:.1%} |
| Average NRI | {snapshot['average_nri']:.1%} |
| Operated locations | {snapshot['operated_fraction']:.1%} |

## Worked question: Wolfcamp A acreage, locations, and value

| Measure | Result |
|---|---:|
| Net WCA acres | {wca['net_acres']:,.2f} acres |
| Unit-schedule WCA net locations | {wca['unit_schedule_net_locations']:,.1f} net wells |
| Undeveloped ComboCurve WCA net locations | {wca['undeveloped_combocurve_net_locations']:,.1f} net wells |
| Undeveloped WCA PV-10 | ${wca['undeveloped_pv10_musd']:,.1f} million |

{wca['note']}

### Worked-answer citations

{worked_sources}

## Production and economics

| Metric | Result |
|---|---:|
| 2024 net production | {production['historical_net_boe'].get('2024', 0):,.0f} BOE |
| 2025 net production | {production['historical_net_boe'].get('2025', 0):,.0f} BOE |
| 2024–2025 decline | {production['historical_decline_2024_to_2025']:.1%} |
| Latest net LOE | ${economics['latest_net_loe_usd_boe']:,.2f}/BOE |
| Latest net oil realization | ${economics['latest_net_oil_usd_bbl']:,.2f}/Bbl |
| Latest net gas realization | ${economics['latest_net_gas_usd_mcf']:,.2f}/Mcf |
| Portfolio PV-10 | ${economics['portfolio_pv10_musd']:,.1f} million |

## Reconciliation and risk

{finding_lines}

## Source files

{citation_lines}
"""
