# Lone Star Basin — Data Room Intelligence Report

Generated from the provenance-aware canonical model. All source data is synthetic.

## Executive snapshot

| Metric | Result |
|---|---:|
| Drilling units | 90 |
| Contractual gross acres | 70,440.39 |
| Economic locations | 640 |
| Producing wells | 320 |
| Average WI | 49.1% |
| Average NRI | 37.7% |
| Operated locations | 75.5% |

## Worked question: Wolfcamp A acreage, locations, and value

| Measure | Result |
|---|---:|
| Net WCA acres | 38,663.82 acres |
| Unit-schedule WCA net locations | 97.0 net wells |
| Undeveloped ComboCurve WCA net locations | 18.8 net wells |
| Undeveloped WCA PV-10 | $356.1 million |

Unit schedule and ComboCurve location counts use different populations and are reported separately rather than silently forced to agree.

### Worked-answer citations

- **net_acres:** `Lone Star Basin Unit Details_vF_2026.08.06.xlsx` — Unit Details zone WCA
- **unit_schedule_net_locations:** `Lone Star Basin Unit Details_vF_2026.08.06.xlsx` — Unit Details zone WCA
- **undeveloped_combocurve_net_locations:** `Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx` — ONELINE!row 327; `Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx` — ONELINE!row 340; `Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx` — ONELINE!row 349; `Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx` — ONELINE!row 356; `Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx` — ONELINE!row 362
- **undeveloped_pv10_musd:** `Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx` — ONELINE!row 327; `Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx` — ONELINE!row 340; `Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx` — ONELINE!row 349; `Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx` — ONELINE!row 356; `Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx` — ONELINE!row 362

## Production and economics

| Metric | Result |
|---|---:|
| 2024 net production | 19,671,750 BOE |
| 2025 net production | 13,640,758 BOE |
| 2024–2025 decline | -30.7% |
| Latest net LOE | $3.73/BOE |
| Latest net oil realization | $63.64/Bbl |
| Latest net gas realization | $0.61/Mcf |
| Portfolio PV-10 | $6,531.7 million |

## Reconciliation and risk

- **WARNING — UNIT_ASSIGNMENT_CONFLICT:** 317 of 320 mapped wells have a ComboCurve UNIT that differs from the unit their GIS lateral overlaps most (e.g. JARDINE 4-27 A 4LS: BADGER_DRAW vs GOLDEN_CROSSING_WEST). Both values are kept for review.
- **WARNING — VALUE_FIELD_CONFLICT:** ONELINE has two '10% Discount Cash Flow (M$)' columns (KY and MF); they disagree for 640 of 640 locations. PV-10 uses KY until the seller confirms which is authoritative.
- **WARNING — OPERATOR_ALIAS_CONFLICT:** 483 of 640 locations list LONE STAR BASIN OPERATING LLC as Current Operator (the briefing's ~75% operated), but 483 of them carry the operator alias NON-OP. The definition of 'operated' needs confirmation.
- **INFO — PDP_COUNT_RECONCILED:** Producing well count reconciles at 320 across ComboCurve and GIS.
- **WARNING — PRICE_SENSITIVITY_UNAVAILABLE:** The room contains one economic price case but no location-level oil/gas sensitivity grid; scenario sensitivity requires rerunning the economics engine.
- **WARNING — AREA_DEFINITION_DIFFERENCE:** Mapped unit footprint exceeds contractual gross acres by 33,721 acres; do not substitute geometry area for ownership acreage.
- **INFO — PDF_GROSS_ACRES_CHECK:** PDF gross acres differ from the canonical workbook value by 0.39 acres.
- **WARNING — FIMU_CONTRACT_PENDING:** The generated FIMU case uses the draft canonical adapter contract because an authoritative FIMU input schema was not supplied.

## Source files

- `LSB Basis Report_2026.09.15.xlsx`
- `LSB LOS_2026.09.17.xlsx`
- `LSB_PDP_20260904.shp`
- `LSB_PF_LEASEHOLD_20260904.shp`
- `LSB_PF_UNITS_20260904.shp`
- `LSB_UNITS_20260806.shp`
- `Lone Star Basin Asset Overview vF_2026.08.05.pdf`
- `Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx`
- `Lone Star Basin Development Model Output_2026.08.06.pdf`
- `Lone Star Basin Unit Details_vF_2026.08.06.xlsx`
