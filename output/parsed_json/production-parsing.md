# Lease Operating Statement production parsing

## Source and row discovery

`LSB LOS_2026.09.17.xlsx` is read with `openpyxl` using calculated cell
values. Every worksheet becomes an `asset_segment`. Row 2 is scanned for
headers that parse exactly as `Month YYYY`. Column A is scanned to locate
`Total LOE` and `Operating Income (Loss)` dynamically.

## Output

`production.json` contains 136 monthly records under
`production`. Segments in this build: `GROSS LSB CENTRAL HZ`, `GROSS LSB V HZ`, `LSBIV NET`, `LSBV NET`.

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
