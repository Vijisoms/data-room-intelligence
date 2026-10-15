# Unit Details parsing

## Source

`Lone Star Basin Unit Details_vF_2026.08.06.xlsx`, worksheet `Unit Details`,
rows 8-97. A row is retained when column C contains a unit name.

## Output

`units.json` contains 90 unit records plus model metadata. It
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
