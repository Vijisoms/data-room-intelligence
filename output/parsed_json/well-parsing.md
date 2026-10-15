# Well and location parsing

## Source

`Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx`,
worksheet `ONELINE`. Excel COM exports the OLE workbook worksheet to a
temporary CSV before pandas reads it.

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
| `api_10` / `api_14` | `API 10` / `API 14` |
| `well_name` | `Well Name`; fallback `well-N` |
| `unit_key` | Normalized `UNIT`, then potentially replaced by GIS reconciliation |
| `operator` | `Current Operator` |
| `status` | Uppercase `WELL STATUS`; fallback `UNKNOWN` |
| `landing_zone` | `Landing Zone` |
| `county` | `County/Parish` |
| `wi` / `nri` | Numeric `WI Oil (%)` / `NRI Oil (%)` |
| `net_boe_mboe` | Numeric `Net BOE Sales Volume (MBBL)` |
| `pv10_musd` | `10% Discount Cash Flow (M$)` divided by 1,000 |
| `irr` | Numeric `Before Income Tax IRR (%)` |
| `source` | ComboCurve path and exact ONELINE row |

The parser does not recalculate PV-10 from monthly cash flow. It normalizes the
source-model result from thousands of dollars to millions of dollars.

## GIS reconciliation

Producing wells are matched to PDP laterals by API-14 and then uppercase well
name. The unit polygon having the longest intersection with a lateral becomes
the reconciled `unit_key`. The supporting spatial result is preserved in
`spatial_links.json` and `well-unit-links.csv`.

## Current identifier caveat

Excel CSV export renders populated API-14 values in scientific notation and
can lose precision. API-10 and retained Chosen ID should be used to audit those
records until API-14 text preservation is corrected.
