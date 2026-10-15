# Pipeline finalization: reconcile, calculate, and write

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

The current finalized model contains 47 metrics.

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
