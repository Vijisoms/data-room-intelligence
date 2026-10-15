# Synthetic Data Room — "Lone Star Basin" (Illustrative)

**This folder contains 100% SYNTHETIC, fictional data.** It mirrors the structure,
file formats, and schema of a real upstream oil & gas M&A data room so collaborators
(e.g., the Microsoft team) can see *what kind of data to expect* — **without exposing
any real, sensitive deal information.**

- No real operator, well, lease, unit, battery, owner, location, price, cost,
  reserve, or economic value appears anywhere in these files.
- All company/asset identifiers are fictional (operator "Lone Star Basin Operating LLC").
- All map geometry is placed in a **neutral, fictional area** (not the real asset's
  location) using synthetic coordinates.
- Every numeric value (ownership %, volumes, prices, revenue, costs, cash flow) is
  randomly generated from plausible industry ranges and is internally consistent but
  **not derived from any real figures.**

## Contents (mirrors the original data room layout)

The synthetic room is in `data/sample-room/`; paths below are relative to it.
The Microsoft briefing deck is in `docs/reference/`.

| File | What it represents |
|------|--------------------|
| `LSB_UNITS_20260806/` (shapefile) | Drilling-unit polygons with NRI/WI by geologic zone |
| `Maps_2026.09.09/LSB - Units_.../` | Pro-forma unit polygons |
| `Maps_2026.09.09/LSB - Leasehold_.../` | Leasehold tract polygons |
| `Maps_2026.09.09/LSB - PDP Sticks_.../` | Producing-well laterals (API, name, operator, landing zone) |
| `Lone Star Basin ComboCurve Oneline ...xlsx` | Economic one-line export (per-well) + monthly cashflow |
| `Lone Star Basin Unit Details ...xlsx` | Unit-level acreage & ownership by zone |
| `September 2026 Updates/LSB Basis Report ...xlsx` | Battery/CTB crude, gas, NGL pricing basis |
| `September 2026 Updates/LSB LOS ...xlsx` | Lease Operating Statements (monthly production, revenue, tax, LOE) |
| `Lone Star Basin Asset Overview ...pdf` | Rough asset-overview slide deck |
| `Lone Star Basin Development Model Output ...pdf` | Rough development-model slide deck |

## How it was generated

See `../tools/` for the reproducible generator:

```powershell
# from the repo root
.\.venv\Scripts\python.exe tools\build_all.py        # regenerate everything
.\.venv\Scripts\python.exe tools\verify_synthetic.py # scan for any residual real identifiers
```

Row counts are representative samples (e.g., ~90 units, ~640 economic locations,
~320 producing wells) rather than the full asset, which is sufficient to convey the
schema. Adjust counts in `tools/synth/config.py`.

## Data Room Intelligence workflow

This repository also contains a Python implementation of the ingestion-to-insight
workflow.

### What it builds

- A provenance-aware canonical model for assets, units, wells, ownership,
  economics, production, pricing and source documents
- Geodesic GIS measurements and a PDP-well-to-unit spatial crosswalk
- Cross-source reconciliation and explicit QA findings
- Standard acquisition answers, including the Wolfcamp A worked example
- A cited Markdown insight report
- A validated draft FIMU case adapter
- Optional Microsoft Foundry-backed Q&A through Microsoft Agent Framework

### Setup

macOS or Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

All parsers are ordinary Python readers (openpyxl, pyshp, pypdf); no Microsoft
Excel installation is needed.

### Configure Azure (keyless)

```bash
cp .env.example .env   # then fill in your Foundry and Document Intelligence endpoints
az login
data-room-intel doctor
```

`doctor` checks the data room, the Azure identity and tenant, a chat call, a
vision call and Document Intelligence, and exits non-zero if any check fails.
Authentication uses Microsoft Entra ID only. Set `AZURE_CLI_SUBSCRIPTION` when
your Azure CLI default tenant differs from the resources' tenant; leave it empty
in Azure so managed identity is used.

### Build the model and report

```bash
data-room-intel build                     # defaults: data/sample-room -> output/
data-room-intel build path/to/room --output out
```

Outputs:

| Output | Purpose |
|---|---|
| `output/canonical-model.json` | Shared, well-keyed canonical model with provenance |
| `output/parsed_json/units.json` | Unit-only canonical records and provenance, without aggregate metrics |
| `output/parsed_json/wells.json` | Well/location-only canonical records and provenance, without aggregate metrics |
| `output/parsed_json/cash_flow.json` | Raw normalized ComboCurve CASHFLOW rows |
| `output/parsed_json/combo_metrics.json` | Metrics derived specifically from ComboCurve |
| `output/parsed_json/spatial_links.json` | JSON form of the GIS well-to-unit crosswalk |
| `output/parsed_json/gis_metrics.json` | Metrics derived specifically from GIS layers |
| `output/parsed_json/production.json` | Monthly LOS production, revenue, LOE, and operating income |
| `output/parsed_json/pdf_facts.json` | Extracted PDF text, facts, and source references |
| `output/parsed_json/pricing.json` | Period-level Basis Report pricing averages |
| `output/well-unit-links.csv` | GIS spatial crosswalk |
| `output/standard-answers.json` | Deterministic answers to recurring deal questions |
| `output/qa-findings.json` | Conflicts, gaps and definition differences |
| `output/insight-report.md` | Consolidated cited deal memo |
| `output/fimu-case.json` | Draft FIMU input contract pending the authoritative schema |

Parsing guides are generated in `output/parsed_json` alongside the data as
`unit-details-parsing.md`, `well-parsing.md`, `cash-flow-parsing.md`,
`combo-metrics-parsing.md`, `spatial-links-parsing.md`, and
`gis-metrics-parsing.md`. The folder also contains `production-parsing.md`,
`pdf-facts-parsing.md`, `pricing-parsing.md`, and `metrics-parsing.md`.
`pipeline-finalization.md` documents reconciliation, analytical metric
calculation, and final output serialization.

### Ask the agent

After configuring `.env` and building:

```bash
data-room-intel ask "What are the Wolfcamp A net acres, net locations and PV-10?"
```

The agent can only query normalized metrics and QA findings. Calculations remain
deterministic and do not depend on the language model.

The checked-in `.env.example` documents every variable and contains no
credentials or environment-specific endpoints.

### Debug with Agent Inspector

After setup and a successful build, press `F5` and select
`Debug Local Agent/Workflow HTTP Server`. The VS Code tasks start the Agent
Framework DevUI endpoint on port 8088 and open Foundry Toolkit Agent Inspector.
