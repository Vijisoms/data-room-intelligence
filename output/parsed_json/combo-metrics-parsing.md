# ComboCurve metrics parsing

## Source

Metrics are derived from the ComboCurve `ONELINE` records and cited to the
`SUMMARY` or `ONELINE` worksheet ranges.

## Output

`combo_metrics.json` contains 5 typed metric records under
`metrics`: `economic_location_count`, `producing_well_count`, `average_wi`, `average_nri`, `operated_location_fraction`.

## Calculations

| Metric | Method |
|---|---|
| `economic_location_count` | Count of ONELINE records |
| `producing_well_count` | Count where normalized status is `PRODUCING` |
| `average_wi` | Sum of parsed WI values divided by record count |
| `average_nri` | Sum of parsed NRI values divided by record count |
| `operated_location_fraction` | Fraction whose operator exactly equals `LONE STAR BASIN OPERATING LLC` |

Each metric includes `name`, `value`, `unit`, optional `dimensions`, source
citations, and an optional calculation method.
