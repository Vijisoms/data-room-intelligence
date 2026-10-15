from __future__ import annotations

from .models import CanonicalModel, Metric


def render_parsing_guides(
    model: CanonicalModel,
    spatial_links: list[dict[str, object]],
    unit_metrics: list[Metric],
    combo_metrics: list[Metric],
    gis_metrics: list[Metric],
) -> dict[str, str]:
    return {
        "unit-details-parsing.md": _unit_details_guide(model),
        "well-parsing.md": _well_guide(model),
        "cash-flow-parsing.md": _cash_flow_guide(model),
        "combo-metrics-parsing.md": _combo_metrics_guide(combo_metrics),
        "spatial-links-parsing.md": _spatial_links_guide(spatial_links),
        "gis-metrics-parsing.md": _gis_metrics_guide(gis_metrics),
        "production-parsing.md": _production_guide(model),
        "pdf-facts-parsing.md": _pdf_facts_guide(model),
        "pricing-parsing.md": _pricing_guide(model),
        "metrics-parsing.md": _metrics_guide(
            model, unit_metrics, combo_metrics, gis_metrics
        ),
        "pipeline-finalization.md": _pipeline_finalization_guide(model),
    }


def _unit_details_guide(model: CanonicalModel) -> str:
    return f"""# Unit Details parsing

## Source

`Lone Star Basin Unit Details_vF_2026.08.06.xlsx`, worksheet `Unit Details`,
rows 8-97. A row is retained when column C contains a unit name.

## Output

`units.json` contains {len(model.units)} unit records plus model metadata. It
does not contain aggregate metrics.

## Column mapping

| Output field | Excel columns | Transformation |
|---|---|---|
| `unit_key` | C | Uppercase unit name; non-alphanumeric runs become `_` |
| `unit_name` | C | Trimmed source text |
| `county` | D | Trimmed source text |
| `development_area` | F | Trimmed source text |
| `gross_acres` | H | Floating-point contractual acreage |
| `lateral_length_ft` | I | Floating-point feet |
| `zone_net_acres` | K:Y | Fifteen values keyed by canonical zone |
| `zone_nri` | AA:AO | Fifteen decimal fractions keyed by zone |
| `zone_wi` | CM:DA | Fifteen decimal fractions keyed by zone |
| `zone_gross_locations` | DS:EG | Fifteen location counts keyed by zone |
| `source` | C:EG for the row | Workbook path, row locator, and as-of date |

Blank numeric zone cells are currently converted to `0.0`; the output does
not distinguish a true zero from an unavailable source value.

## Zones

`USS`, `MSS`, `JM`, `LSS`, `DEAN`, `WCA`, `WCB I`, `WCB II`, `WCC`, `WCD`,
`STR / BND`, `UP BRNT`, `LR BRNT`, `MSSP`, and `WDFD`.

## Derived metrics

Unit metrics remain in `canonical-model.json`, not `units.json`. Net acreage
is summed from unit-level zone net acres. Net locations are calculated as the
sum of `zone_gross_locations × zone_wi`.
"""


def _well_guide(model: CanonicalModel) -> str:
    return f"""# Well and location parsing

## Source

`Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx`,
worksheet `ONELINE`, read natively with `openpyxl` (cached values). Row 1 is the
header; every non-blank row below it is one location.

## Output

`wells.json` contains {len(model.wells)} well and economic-location records
plus model metadata. It does not contain aggregate metrics.

## Identifier selection

`well_key` remains backward compatible and uses this priority:

1. `API 14`
2. `Chosen ID`
3. normalized `Well Name`

`chosen_id` retains the original Chosen ID, and `well_key_source` records
whether the selected key came from `api_14`, `chosen_id`, or `well_name`.

## Field mapping

| Output field | ONELINE column or rule |
|---|---|
| `well_key` | Identifier priority described above |
| `chosen_id` | `Chosen ID` |
| `well_key_source` | Derived identifier provenance |
| `api_10` / `api_14` | `API 10` / `API 14`, normalized to zero-padded digit text |
| `well_name` | `Well Name`; fallback `well-N` |
| `unit_key` | Normalized `UNIT` (the source assignment; never overwritten) |
| `spatial_unit_key` | Unit whose GIS polygon the PDP lateral overlaps most (producing wells) |
| `operator` / `operator_alias` | `Current Operator` / `Current Operator Alias` |
| `status` | Uppercase `WELL STATUS`; fallback `UNKNOWN` |
| `landing_zone` | `Landing Zone` |
| `county` | `County/Parish` |
| `wi` / `nri` | Numeric `WI Oil (%)` / `NRI Oil (%)`; the source already holds fractions |
| `net_boe_mboe` | Numeric `Net BOE Sales Volume (MBBL)` |
| `pv10_musd` | `10% Discount Cash Flow (M$)` (column KY) divided by 1,000 |
| `pv10_alt_musd` | Second `10% Discount Cash Flow (M$)` column (MF) divided by 1,000 |
| `irr` | `IRR (%)` percentage points divided by 100 (fraction) |
| `source` | ComboCurve path and exact ONELINE row |

The parser does not recalculate PV-10 from monthly cash flow. It normalizes the
source-model result from thousands of dollars to millions of dollars. The
workbook has two `10% Discount Cash Flow (M$)` columns that disagree; both are
kept and `VALUE_FIELD_CONFLICT` reports the difference.

## GIS reconciliation

Producing wells are matched to PDP laterals by API-14 and then uppercase well
name. The unit polygon having the longest intersection with a lateral is stored
as `spatial_unit_key`. The source `unit_key` is kept, and disagreements are
reported as `UNIT_ASSIGNMENT_CONFLICT`. The spatial result is also in
`spatial_links.json` and `well-unit-links.csv`.

## Identifiers

Excel stores API numbers as numbers and the GIS layer stores them as text. Both
are normalized to zero-padded digit text, so the 320 producing wells keep 320
unique API-14 values and join to GIS by API-14.
"""


def _cash_flow_guide(model: CanonicalModel) -> str:
    fields = sorted(
        {str(key) for record in model.cash_flow for key in record}
    )
    field_text = ", ".join(f"`{field}`" for field in fields)
    return f"""# ComboCurve cash-flow parsing

## Source and method

The ComboCurve `CASHFLOW` worksheet is read natively with `openpyxl` (cached
values). Its first row becomes the header; duplicate header names get `.1`,
`.2` suffixes. Every non-blank row is converted to a record dictionary.

## Output

`cash_flow.json` contains {len(model.cash_flow)} records under `cash_flow`.
The parser intentionally preserves the source worksheet's wide schema rather
than mapping it into the typed well schema.

## Fields found in this build

{field_text or "No cash-flow fields were found."}

## Important behavior

- No PV-10 is recalculated from these rows.
- Cell values keep their workbook types; dates become ISO 8601 text.
- Column names follow the worksheet header.
- The output is raw normalized transport data for later economics validation.
"""


def _combo_metrics_guide(metrics: list[Metric]) -> str:
    names = ", ".join(f"`{metric.name}`" for metric in metrics)
    return f"""# ComboCurve metrics parsing

## Source

Metrics are derived from the ComboCurve `ONELINE` records and cited to the
`SUMMARY` or `ONELINE` worksheet ranges.

## Output

`combo_metrics.json` contains {len(metrics)} typed metric records under
`metrics`: {names or "none"}.

## Calculations

| Metric | Method |
|---|---|
| `economic_location_count` | Count of ONELINE records |
| `producing_well_count` | Count where normalized status is `PRODUCING` |
| `average_wi` | Sum of parsed WI values divided by record count |
| `average_nri` | Sum of parsed NRI values divided by record count |
| `operated_location_fraction` | Fraction whose operator exactly equals `LONE STAR BASIN OPERATING LLC`; unconfirmed, because those locations carry the alias `NON-OP` (`OPERATOR_ALIAS_CONFLICT`) |

Each metric includes `name`, `value`, `unit`, optional `dimensions`, source
citations, and an optional calculation method.
"""


def _spatial_links_guide(spatial_links: list[dict[str, object]]) -> str:
    return f"""# Spatial well-to-unit link parsing

## Sources

- September unit polygons
- September leasehold polygons
- September PDP lateral line features

The shapefile attribute rows and geometries are read in matching order.

## Output

`spatial_links.json` contains {len(spatial_links)} records under
`spatial_links`. The same records are also written to `well-unit-links.csv`.

## Matching algorithm

For each PDP lateral, the parser:

1. Finds every unit polygon intersecting the lateral.
2. Measures the geometry intersection length for every candidate.
3. Selects the unit having the maximum intersection length.
4. Tests whether the lateral intersects the dissolved leasehold geometry.

## Schema

| Field | Source or derivation |
|---|---|
| `api_10` | PDP shapefile `API_10`, zero-padded digit text |
| `api_14` | PDP shapefile `API_14`, zero-padded digit text |
| `well_name` | PDP shapefile `Well_Name` |
| `landing_zone` | PDP shapefile `Landing_Zo` |
| `unit_name` | Selected intersecting unit polygon `UNIT_NAME` |
| `unit_key` | `unit_name` normalized like Unit Details keys |
| `intersects_leasehold` | Boolean spatial intersection with dissolved leasehold |

An unmatched lateral has a null `unit_name`.
"""


def _gis_metrics_guide(metrics: list[Metric]) -> str:
    names = ", ".join(f"`{metric.name}`" for metric in metrics)
    return f"""# GIS metrics parsing

## Output

`gis_metrics.json` contains {len(metrics)} typed metric records under
`metrics`: {names or "none"}.

## Calculations

| Metric | Method |
|---|---|
| `mapped_unit_area` | WGS84 geodesic area of dissolved unit polygons, converted from square metres to acres |
| `active_leasehold_area` | WGS84 geodesic area of dissolved leasehold polygons, converted to acres |
| `pdp_lateral_count` | Number of PDP line features |
| `pdp_laterals_intersecting_leasehold` | Count of lateral geometries intersecting dissolved leasehold |

Area is calculated with `pyproj.Geod(ellps="WGS84")`; raw longitude/latitude
degree area is not used. Every metric includes source file provenance and its
calculation method where applicable.
"""


def _production_guide(model: CanonicalModel) -> str:
    segments = sorted({item.asset_segment for item in model.production})
    return f"""# Lease Operating Statement production parsing

## Source and row discovery

`LSB LOS_2026.09.17.xlsx` is read with `openpyxl` using calculated cell
values. Every worksheet becomes an `asset_segment`. Row 2 is scanned for
headers that parse exactly as `Month YYYY`. Column A is scanned to locate
`Total LOE` and `Operating Income (Loss)` dynamically.

## Output

`production.json` contains {len(model.production)} monthly records under
`production`. Segments in this build: {", ".join(f"`{item}`" for item in segments)}.

## Field mapping

| Field | Source |
|---|---|
| `asset_segment` | Worksheet title |
| `month` | Row 2 month header, normalized to ISO `YYYY-MM-DD` |
| `oil_bbl` | Row 3 |
| `gas_mcf` | Row 4 |
| `ngl_bbl` | Row 5 |
| `boe` | Row 6 |
| `revenue_usd` | Row 12 when numeric |
| `loe_usd` | Dynamically located `Total LOE` row |
| `operating_income_usd` | Dynamically located `Operating Income (Loss)` row |
| `source` | Workbook path and the month column from row 2 through row 12 |

A month is skipped unless all four production-volume cells are numeric.
Revenue, LOE, and operating income may be JSON `null`.
"""


def _pdf_facts_guide(model: CanonicalModel) -> str:
    files = ", ".join(f"`{name}`" for name in model.pdf_facts)
    return f"""# PDF facts parsing

## Source and extraction

Every discovered PDF is opened with `pypdf.PdfReader`. Text extracted from all
pages is concatenated with newline separators. No OCR is currently applied, so
image-only content is not converted to text.

## Output

`pdf_facts.json` contains {len(model.pdf_facts)} file entries under
`pdf_facts`: {files or "none"}.

Each entry contains `page_count`, full extracted `text`, regex-derived
`metrics`, and a whole-file `source` reference.

## Recognized metric labels

`Drilling Units`, `Gross Acres`, `Producing Wells (PDP)`,
`Total Econ Locations`, `D&C Capital ($MM)`, `EUR (MBOE)`, `PV-10 ($MM)`,
`IRR (%)`, `Payout (months)`, and `Breakeven ($/Bbl WTI)`.

Only the first regex match for each label is retained. Missing or differently
formatted labels are omitted rather than defaulted to zero.
"""


def _pricing_guide(model: CanonicalModel) -> str:
    periods = ", ".join(f"`{item['period']}`" for item in model.pricing)
    return f"""# Basis and pricing parsing

## Source and row filtering

`LSB Basis Report_2026.09.15.xlsx` is read with `openpyxl` using calculated
values. The first worksheet is skipped. In each remaining period worksheet,
rows C:AB beginning at row 10 are retained when column C is populated, the
relative type column equals `HORZ`, and the required numeric value is present.

## Output

`pricing.json` contains {len(model.pricing)} period records under `pricing`.
Periods in this build: {periods or "none"}.

## Aggregation

Each output record contains the worksheet title, retained facility count, and
the arithmetic mean of available numeric values for oil NYMEX, oil basis, net
oil realization, Henry Hub gas, gas basis, net gas realization, and NGL price.
Missing numeric observations are excluded from each individual average.

`source` cites the complete scanned range for the period worksheet.
"""


def _metrics_guide(
    model: CanonicalModel,
    unit_metrics: list[Metric],
    combo_metrics: list[Metric],
    gis_metrics: list[Metric],
) -> str:
    parsed_count = len(unit_metrics) + len(combo_metrics) + len(gis_metrics)
    analytic_count = len(model.metrics) - parsed_count
    return f"""# Canonical metrics derivation

## Initial composition

The pipeline initializes the canonical collection exactly as:

```python
metrics = unit_metrics + combo_metrics + gis_metrics
```

| Metric family | Count | Source |
|---|---:|---|
| Unit Details | {len(unit_metrics)} | Contractual acreage, ownership, and unit location schedule |
| ComboCurve | {len(combo_metrics)} | Economic well/location records |
| GIS | {len(gis_metrics)} | Unit, leasehold, and PDP geometries |
| **Initial parsed metrics** | **{parsed_count}** | Concatenation in the order above |

Metric records share the schema `name`, `value`, `unit`, `dimensions`,
`sources`, and `method`.

## Unit metrics

The unit parser creates `unit_count`, `gross_acres`, `county_count`, and
`development_area_count`, plus `net_acres` and `net_locations` for each of 15
zones. Zone net locations equal the sum of unit gross locations multiplied by
unit WI.

## ComboCurve metrics

The ComboCurve parser creates `economic_location_count`,
`producing_well_count`, `average_wi`, `average_nri`, and
`operated_location_fraction`.

## GIS metrics

The GIS parser creates `mapped_unit_area`, `active_leasehold_area`,
`pdp_lateral_count`, and `pdp_laterals_intersecting_leasehold`.

## Post-reconciliation analytics

After the three parsed lists are assigned, reconciliation adds QA findings but
does not add metrics. `calculate_metrics(model)` then appends
{analytic_count} analytical metrics in this build: undeveloped WCA gross
location count, undeveloped WCA net locations, undeveloped WCA PV-10, and
latest monthly net production when production records are available.

The final `canonical-model.json` contains {len(model.metrics)} metrics. The
standalone `combo_metrics.json` and `gis_metrics.json` remain source-family
outputs and intentionally exclude later analytical metrics.
"""


def _pipeline_finalization_guide(model: CanonicalModel) -> str:
    return f"""# Pipeline finalization: reconcile, calculate, and write

The pipeline finishes in a strict sequence:

```python
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
```

Both `reconcile` and `calculate_metrics` mutate the in-memory
`CanonicalModel`. `write_outputs` must run last so every persisted artifact
contains the reconciled keys, QA findings, and appended analytical metrics.

## 1. `reconcile(model, spatial_links)`

### Well-to-GIS matching

Two lookup indexes are built from `spatial_links`: one by nonblank API-14 and
one by uppercase well name. Each canonical well is matched by API-14 first and
well name second. For a match having a GIS unit, the spatially selected unit is
stored in `spatial_unit_key`. The ComboCurve `unit_key` is never replaced.

### Cross-source QA findings

Reconciliation appends findings to `model.findings`:

| Finding | Condition |
|---|---|
| `PDP_COUNT_MISMATCH` | Producing ComboCurve count differs from GIS PDP lateral count |
| `PDP_COUNT_RECONCILED` | The two PDP counts agree |
| `PRICE_SENSITIVITY_UNAVAILABLE` | The reconciled case has no location-level sensitivity grid |
| `WELL_KEY_GAPS` | Not every GIS lateral matches a canonical well |
| `AREA_DEFINITION_DIFFERENCE` | GIS footprint area differs from contractual gross acres |
| `PDF_GROSS_ACRES_CHECK` | PDF acreage is compared with workbook contractual acreage |
| `UNITS_WITHOUT_WELLS` | Some Unit Details keys have no economic well/location |
| `FIMU_CONTRACT_PENDING` | The generated FIMU case uses the draft adapter contract |
| `UNIT_ASSIGNMENT_CONFLICT` | ComboCurve `UNIT` differs from the GIS-selected unit |
| `VALUE_FIELD_CONFLICT` | The two `10% Discount Cash Flow (M$)` columns disagree |
| `OPERATOR_ALIAS_CONFLICT` | Seller-operated locations carry the alias `NON-OP` |

Reconciliation does not silently replace contractual acreage with GIS area,
or source unit assignments with map results. It preserves both values and
records the difference as a QA warning.

## 2. `calculate_metrics(model)`

This step appends analytical metrics after the parsed Unit Details,
ComboCurve, and GIS metrics are already present.

For non-producing wells whose landing zone is exactly `WOLFCAMP A`, it adds:

- `location_count`: number of undeveloped WCA records.
- `combocurve_net_locations`: sum of their working interests.
- `pv10`: sum of their location-level `pv10_musd` values.

When LOS production exists, it also finds the latest month, selects segments
whose worksheet names end in `NET`, and adds `latest_net_production` as the
sum of their BOE.

The current finalized model contains {len(model.metrics)} metrics.

## 3. `write_outputs(...)`

The writer creates the output directories, serializes the finalized canonical
model, derives standard answers and the FIMU case, renders the report, and
writes source-family datasets and parsing guides.

### Root `output` artifacts

- `canonical-model.json`
- `standard-answers.json`
- `qa-findings.json`
- `fimu-case.json`
- `insight-report.md`
- `well-unit-links.csv`

### `output/parsed_json` artifacts

- Unit, well, cash-flow, production, PDF-fact, and pricing JSON.
- ComboCurve metrics, GIS metrics, and spatial-link JSON.
- Parsing and derivation Markdown guides.

`standard_answers(model)` reads the now-reconciled and fully calculated model.
`build_fimu_case(model)` adapts that same state into the draft FIMU contract.
The Markdown insight report is rendered from the standard answers and source
citations.

Finally, `write_outputs` returns a `PipelineResult` containing absolute paths
for the canonical model, report, FIMU case, QA file, and output directory.

## Ordering requirement

Changing the order changes persisted behavior:

- Writing before reconciliation would omit spatial unit keys and QA findings.
- Writing before metric calculation would omit WCA analytics and latest net
  production.
- Calculating before reconciliation would currently produce the same WCA sums,
  but it would violate the intended contract that all analytics operate on the
  reconciled canonical model.

The required lifecycle is therefore:

```text
Parsed canonical model
    → reconcile identities and sources
    → append analytical metrics
    → serialize all outputs
    → return output paths
```
"""
