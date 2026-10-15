# PDF facts parsing

## Source and extraction

Every discovered PDF is opened with `pypdf.PdfReader`. Text extracted from all
pages is concatenated with newline separators. No OCR is currently applied, so
image-only content is not converted to text.

## Output

`pdf_facts.json` contains 2 file entries under
`pdf_facts`: `Lone Star Basin Asset Overview vF_2026.08.05.pdf`, `Lone Star Basin Development Model Output_2026.08.06.pdf`.

Each entry contains `page_count`, full extracted `text`, regex-derived
`metrics`, and a whole-file `source` reference.

## Recognized metric labels

`Drilling Units`, `Gross Acres`, `Producing Wells (PDP)`,
`Total Econ Locations`, `D&C Capital ($MM)`, `EUR (MBOE)`, `PV-10 ($MM)`,
`IRR (%)`, `Payout (months)`, and `Breakeven ($/Bbl WTI)`.

Only the first regex match for each label is retained. Missing or differently
formatted labels are omitted rather than defaulted to zero.
