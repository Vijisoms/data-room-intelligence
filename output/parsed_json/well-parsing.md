# Well and location parsing

## Source

`Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx`,
worksheet `ONELINE`, read natively with `openpyxl` (cached values). Row 1 is the
header; every non-blank row below it is one location.

## Output

`wells.json` contains 640 well and economic-location records
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
