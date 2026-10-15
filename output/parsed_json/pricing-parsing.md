# Basis and pricing parsing

## Source and row filtering

`LSB Basis Report_2026.09.15.xlsx` is read with `openpyxl` using calculated
values. The first worksheet is skipped. In each remaining period worksheet,
rows C:AB beginning at row 10 are retained when column C is populated, the
relative type column equals `HORZ`, and the required numeric value is present.

## Output

`pricing.json` contains 7 period records under `pricing`.
Periods in this build: `LSB Basis Report - Jan26`, `LSB Basis Report - Feb26`, `LSB Basis Report - Mar26`, `LSB Basis Report - Apr26`, `LSB Basis Report - May26`, `LSB Basis Report - Jun26`, `LSB Basis Report-Jul26`.

## Aggregation

Each output record contains the worksheet title, retained facility count, and
the arithmetic mean of available numeric values for oil NYMEX, oil basis, net
oil realization, Henry Hub gas, gas basis, net gas realization, and NGL price.
Missing numeric observations are excluded from each individual average.

`source` cites the complete scanned range for the period worksheet.
