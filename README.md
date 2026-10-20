# Data Room Intelligence

Data Room Intelligence turns an upstream oil and gas M&A data room (workbooks, PDF decks
and map layers) into a reviewed, cited knowledge graph: entities such as units, wells and
economic locations with their facts, every value traced to its cell, page or map feature,
disagreements between files flagged for a decision, a chat that answers with citations,
and a web app that leads the deal team through the work in five steps:

```text
 Projects ─▶ 1 Data ─▶ 2 Model ─▶ 3 Decisions ─▶ 4 Publish ─▶ 5 Ask
```

Each data room is a **project**. Every project starts from the same governed base model
(`ontology/catalog.yaml`); when a file brings a kind of data the model lacks, the system
proposes a model change and the data steward approves it, so the model grows with the data
without the base being edited. [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) explains the
design in detail.

Contents

1. [Quick start with the sample room](#1-quick-start-with-the-sample-room)
2. [Bring your own data room, step by step](#2-bring-your-own-data-room-step-by-step)
3. [The screens](#3-the-screens)
4. [The sample room and the mock scenario files](#4-the-sample-room-and-the-mock-scenario-files)
5. [Command line](#5-command-line)
6. [Settings](#6-settings)
7. [Troubleshooting](#7-troubleshooting)
8. [Developing](#8-developing)

---

## 1. Quick start with the sample room

Requirements: Python 3.11+, Node.js 20.19+ or 22.12+ (for the web UI build), and, for the
live model features, access to an Azure AI Foundry project (keyless, Entra ID). Everything
except the live model runs offline from a seeded cache.

```bash
# 1. Install
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"      # Windows: .\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 2. (Optional) connect Azure; skip this and use DRI_OFFLINE=1 below instead
cp .env.example .env                              # fill in the Foundry and Document Intelligence endpoints
az login
.venv/bin/data-room-intel doctor                  # checks the room, identity, chat, vision and Document Intelligence

# 3. Build the web UI once
(cd frontend && npm ci && npm run build)

# 4. Build the sample snapshot and start the app
.venv/bin/data-room-intel snapshot                # offline: DRI_OFFLINE=1 .venv/bin/data-room-intel snapshot
.venv/bin/data-room-intel serve --port 8765       # offline: DRI_OFFLINE=1 .venv/bin/data-room-intel serve --port 8765
```

Open http://127.0.0.1:8765. The Projects page shows *Lone Star Basin*, the synthetic sample
room (10 files, 2,307 decisions blocking). Click **Open** and walk the steps, or follow
[section 4](#4-the-sample-room-and-the-mock-scenario-files) to try the three mock files that
show how a project grows. If the browser shows an older version of the app, hard-reload
(Cmd/Ctrl+Shift+R).

The server listens on 127.0.0.1 only and has no sign-in; do not expose it on a network.

---

## 2. Bring your own data room, step by step

This is the end-to-end path for a real data room. It assumes the install from the quick
start. Nothing here needs the sample room; the sample project can stay or be ignored.

### Step 0. Know what the system does with each file

Files are read by format, then routed by name.

| You add | What is read | Where it goes |
|---|---|---|
| `.xlsx`, `.xlsm` | Every sheet; each table region is profiled (types, units from headers, null rates, candidate keys). Formula cells without a saved value are flagged, never read as zero. Rights-managed workbooks are detected and skipped | Tables go to field mapping (Step 4) |
| `.csv`, `.tsv`, `.txt` | One table per file, delimiter and encoding detected | Field mapping |
| `.pdf` | Pages, paragraphs, tables and figure regions (Azure Document Intelligence), charts read by the vision model, headline numbers extracted as claims and checked against the data. **Offline**: plain text only | Data step viewer; claims become issues when they disagree |
| `.shp` with its sidecars (`.shx`, `.dbf`, `.prj`, …) | Features and attributes; geodesic acres and lengths; spatial relationships between units, laterals and tracts | Map view; spatial links |
| `.zip` | Unpacked as uploaded, folders kept, so a whole data room or a shapefile bundle can be added at once (`.pptx`, images and other formats inside are ignored) | As above, per file |

**File names matter for the built-in recipes.** Files whose names contain `unit details`,
`combocurve`, `los`, `basis`, `asset overview`, `development model`, `pdp`, `leasehold` or
`units` are routed to the recipes written for the sample room's layouts. Each recipe first
checks that the layout matches (for example an economics one-line must have `INPT ID`,
`API 14`, `Well Name`, `UNIT`, `Current Operator` and `Project Name` columns); if it does not,
the file is treated like any other and mapped in Step 4. Map layers link to units by a
`UNIT_NAME`/`UNIT` attribute and to wells by `API_14`; features without them stay in the
extracted layer but do not become entities.

Everything else (a lease schedule, an AFE register, a reserves export, a production file, a
crosswalk) is **generic**: its columns are matched against the model from the values and
headers, and whatever the model cannot place becomes a proposed model change.

### Step 1. Create the project

In the app, on the Projects page, fill in **New project**:

- **Project name**: becomes the project ID (`Delaware Basin Package B` → `delaware-basin-package-b`).
- **Starting model**: *Upstream deal template* (the governed base model) or *Copy a project's
  model* (base model plus the entity types, relationships and header rules another project
  approved; useful when the same seller sends a second package).

Click **Create project**. The project opens on the Data step, empty.

From the command line instead, point `snapshot` at a folder; the project is registered and
built in one go:

```bash
.venv/bin/data-room-intel snapshot /path/to/data-room --room-id delaware-basin-package-b
```

### Step 2. Add the files

On the Data step click **Upload files or a zip** and choose a zip of the data room, or add
files one at a time (up to 200 MB per upload). Each upload:

1. copies the file under `.dri-data/rooms/<project>/incoming/` (originals are never modified);
2. rebuilds the snapshot: discovery, extraction of every file, model building, checks;
3. tells you what happened in a message, and moves you to the step that needs you:
   - files the model understands are read at once and you stay on Data;
   - columns that need a decision send you to **Model → Field mappings**;
   - a file that brings a new kind of data sends you to **Model → Changes**.

A rebuild of the sample room (10 files) takes a few seconds offline; PDFs take longer the
first time because Document Intelligence and the vision model run (results are cached by
file hash).

### Step 3. Check what was read (Data)

The file list groups workbooks, documents and map layers; files added to the project are
marked. Click a file:

- **Sheets**: a windowed grid; mapped columns are underlined (green approved, amber
  proposed); click a cell for its mapping, the facts it produced, the entities it feeds and
  the issues that cite it. Formula cells without a value are shown as `=ƒ (no cache)`.
- **PDFs**: pages with text, figure and claim overlays; each headline number marked as
  matching the data or not; extracted chart values and their cross-check.
- **Map layers**: units, tracts and laterals; conflicts in red; click a feature for its
  attributes and entity.

If a table was read with the wrong header row, or a file that should have been generic
went through a recipe, rename the file (so it no longer matches a recipe name) and upload
it again.

### Step 4. Teach the model what it does not know yet (Model)

The Model step header shows the project's model version (`0.1.0` for the base model;
`0.1.0+<project>.N` after N approved changes) and what is waiting.

**Field mappings.** For a table whose rows the model recognises (its key column matched
existing wells, units, battery codes, …), each remaining column is proposed as a property,
measure, dimension or link of that type, with the evidence: *header rule*, *value overlap*
(for example *240 of 252 values match an existing Well*) or *model proposal* with a
confidence and a one-sentence rationale. Approve or reject each, then **Rebuild**. A link
that fills a declared gap (a relationship with no links yet) is marked. Decisions are
remembered by header, so the next file with the same headers maps without another review.

**Changes.** When a file cannot be placed, a model change is proposed with its evidence:

- *New entity type*: no column matches an existing key, but one column identifies the rows.
  The proposal names the type, its key, properties (text and date columns), measures
  (numeric columns, unit read from the header) and relationships (columns whose values match
  existing units, counties, wells, …), plus one header rule per column.
- *Extend an existing type*: the rows are wells or units but some columns fit nothing the
  type has.
- *Link two types*: the file is a crosswalk between two existing types without a declared
  relationship.

Review the names (every name is editable; header rules and mappings follow), type a reason,
and **Approve and rebuild**. The change is appended to the project's change log, the model
version increases, the snapshot is rebuilt with the new type, and you land on Publish to see
what changed. **Reject** keeps the file in the room without modelling it.

The base model is never edited from the app. **Dictionary** shows the model with base and
project items told apart; **Graph** shows it as a schema graph with the project's types in
a row below the base types.

### Step 5. Settle the disagreements (Decisions)

Checks run on every rebuild and raise one issue per conflicting item: the same well in two
different units, two columns with the same header and different values, a slide number that
does not match the data, rows of a new file that name an entity the room does not have, and
so on. Blocking issues hold publishing.

The Decisions step shows one card per question, in business wording, with the discipline
that usually owns it. Type a reason and pick an answer to decide **for all** affected items at
once ("Use GIS unit" for 317 wells), or open **Review one by one** for the side-by-side
evidence with citations and a map. Decisions are append-only with reviewer, reason, scope and
snapshot; both source values stay in the graph. Because issue IDs are stable, a decision keeps
applying when the files are updated and the issue reappears.

Decisions change the answers: once the PV-10 column is decided, questions get a single PV-10
and say which decision it rests on.

### Step 6. Publish and export (Publish)

The Publish step shows the current snapshot (ID, build time, model version, contents), the
gate (which questions still block, or **Publish snapshot** when none does; publishing with
open issues needs a named reviewer and a reason, recorded in the snapshot), **What changed**
against the previous or any earlier snapshot (files added or replaced, entities and links
added or removed, values that changed, issues new or resolved), the snapshot history, and
CSV exports: the decision log, the entities, and every fact with its file and cell, page or
feature.

### Step 7. Ask questions (Ask)

The Ask step shows the connected picture, a schema graph or the neighbourhood of any entity
(search with `/`), with the chat beside it. The chat calls named operations only (room
overview, zone summary, unit and well profiles, locations, conflicts, claim check, gap
report, lineage); every number in an answer must appear in an operation result, answers cite
the cells, pages and map features they rest on, and buttons open the cited source, the
entity or the decision. Offline, a keyword router answers from the same operations. The
**Ask** button in the top bar opens the chat on any step.

### Step 8. When the seller sends an update

Upload the new version of a file with the same name. The snapshot is rebuilt, decisions
recorded on earlier snapshots keep applying, and **What changed** on the Publish step lists
the new, removed and changed entities, values and issues. The previous snapshots stay on
disk and in the history.

### Resetting and removing

- Remove a file: delete it from `.dri-data/rooms/<project>/incoming/` and rebuild (`POST
  /api/rebuild?room=<project>` or the **Rebuild** button on Model → Field mappings).
- Reset the project's decisions or model changes: delete `reviews/` or `catalog/` under the
  project folder and rebuild.
- Delete a project: `curl -X DELETE http://127.0.0.1:8765/api/projects/<project>` (the sample
  project cannot be deleted).

### What runs offline and what needs Azure

| Feature | Offline (`DRI_OFFLINE=1`) | With Azure |
|---|---|---|
| Workbooks, CSVs, map layers, checks, decisions, snapshots, exports | Yes | Yes |
| PDFs | Plain text; no layout, figures or chart values (the sample room's PDFs come from a seeded cache) | Document Intelligence layout, vision model for charts |
| Field mappings the rules cannot decide | Keyword heuristic for oil, gas, water and days columns | gpt-6-astra proposes targets with a rationale |
| Names of a proposed model change | Derived from headers (`Lease`, `LEASE_IN_UNIT`) | gpt-6-astra drafts names, descriptions and OSDU hints |
| Chat | Keyword router over the named operations | gpt-6-astra with the operations as tools; numbers verified |

### Known limits for your own data

- Shapes that need code remain code: a workbook with several header rows or repeated blocks
  per zone (like the sample Unit Details) needs a family extractor; a new format such as LAS
  well logs needs a parser. Tables with one header row are modelled from their columns.
- Spatial links (lateral in unit, tract in unit, lateral crosses tract) are computed when a
  room has a units layer, a laterals (`pdp`) layer and a `leasehold` layer.
- Checks are the base rules (unit assignment, ownership values, duplicate value columns,
  zone aliases, operator alias, pricing crosswalk, uncached formulas, document claims,
  unmatched keys and links). New rules are YAML plus a small function in
  `ontology/rules.py`.
- The server runs locally without sign-in; the reviewer name on a decision is typed, not
  authenticated.

---

## 3. The screens

| Screen | What it shows |
|---|---|
| Projects | One card per data room: files, model version, items to review, decisions blocking, last build; **New project** from the base model or another project's model |
| 1 Data | Every file with its sheets, pages or map; mapped columns and cell lineage; claim and chart checks; add files |
| 2 Model | **Changes** (proposed model changes, editable, with evidence and a change log), **Field mappings** (columns to approve), **Dictionary** (the model, base and project items marked), **Graph** (schema graph) |
| 3 Decisions | One card per question; decide for all with a reason, or review one by one with side-by-side evidence |
| 4 Publish | Snapshot status and gate, what changed, snapshot history, CSV exports |
| 5 Ask | Graph and chat; answers cite sources and follow recorded decisions |

The URL hash keeps the project and the place, so any screen can be shared as a link:
`#room=lone-star-basin&view=data&fileId=combocurve&sheet=ONELINE&cell=KY2` opens a cell and
its lineage; `#room=…&view=decisions&rule=VALUE_FIELD_CONFLICT&queue=1` opens a decision
queue. Links written for the earlier views (`#view=inputs`, `review`, `schema`, `explore`)
still open the matching step. Add `&theme=light` or `&chat=on` as needed.

---

## 4. The sample room and the mock scenario files

### The sample room (synthetic)

**`data/sample-room/` contains 100% synthetic, fictional data.** It mirrors the structure,
file formats and schema of a real upstream oil and gas M&A data room so collaborators can
see what kind of data to expect, without exposing any real deal information. No real
operator, well, lease, unit, battery, owner, location, price, cost, reserve or economic value
appears anywhere in these files; identifiers are fictional (operator "Lone Star Basin
Operating LLC"); map geometry is placed in a neutral, fictional area; every numeric value is
randomly generated from plausible industry ranges, internally consistent but not derived
from any real figures.

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

About 90 units, 640 economic locations and 320 producing wells: enough to convey the schema.
The sample room builds 1,596 entities, 4,928 links and 38,463 facts, with 2,307 blocking
issues (317 unit assignment conflicts, 1,350 ownership value conflicts, 640 duplicate value
columns).

### Three mock files that show how a project grows

Under `data/scenarios/`. **None is a customer file**; each imitates something a seller would
send, and each has a generator (`make_*.py`) that documents its design. Add them to the
sample project from the Data step:

| File | What happens | Who approves |
|---|---|---|
| `crosswalk/Battery Facility Crosswalk_2026.09.xlsx` | Battery codes match `BatteryCode.code` (92 of 94), facilities match `PricingFacility.name`, and the model already declares `PRICED_AT` between them: two mappings fill the gap, 92 links appear, `CROSSWALK_MISSING` disappears, price questions become supportable; 2 unknown battery codes raise `UNMATCHED_KEY` | Reviewer approves two field mappings |
| `new-concept/Lease Schedule_2026.09.xlsx` | No existing key matches; `Lease No.` identifies the 124 rows and the Unit and County columns match existing entities. A **model change** is proposed: a new `Lease` type with four properties, three measures, two relationships and ten header rules | Data steward reviews the names and approves; the model becomes `0.1.0+lone-star-basin.1`, 124 leases enter the graph with cell citations, 2 rows naming an unknown unit raise `UNMATCHED_LINK` |
| `new-dataset/Seller Well Production_2026.07.xlsx` | Rows are wells (API numbers with dashes match 240 of 252 values); *Production Month* is matched by a header rule and the other columns are proposed as well measures. After approval 960 monthly facts attach to 40 wells; 2 unknown wells raise `UNMATCHED_KEY`; "What did JARDINE 4-27 A 4LS produce in June 2026?" becomes answerable | Reviewer approves five field mappings once |

To reset the sample project after trying them:

```bash
rm -rf .dri-data/rooms/lone-star-basin          # uploads, decisions, model changes and snapshot history
.venv/bin/data-room-intel snapshot
```

---

## 5. Command line

| Command | What it does |
|---|---|
| `data-room-intel doctor [--data-room DIR]` | Checks the data room folder, the Azure identity and tenant, a chat call, a vision call and Document Intelligence; exits non-zero on failure |
| `data-room-intel catalog validate` / `catalog export --out docs/catalog` | Validates `ontology/catalog.yaml` (14 entity types, 15 relationship types, 27 measures) and renders the dictionary, Mermaid, JSON Schema and Turtle |
| `data-room-intel ingest [DIR] [--room-id ID]` | Bronze copy and manifest, then Silver: GIS features and spatial candidates, staged workbook values, PDF layout, figures and claims |
| `data-room-intel snapshot [DIR] [--room-id ID]` | Registers the project if needed and runs the Agent Framework workflow: discover, then GIS, tabular and PDF tracks in parallel, model building, mapping and model-change proposals, checks and the review gate. Writes Gold tables, `ontology.duckdb`, `catalog.json` and `snapshot.json` |
| `data-room-intel ask "question" [--room-id ID]` | Answers from the named operations over the latest snapshot, with citations |
| `data-room-intel publish-snapshot [--room-id ID] [--force --reviewer NAME --reason TEXT]` | Publishes when no blocking issue is open; forcing records who and why |
| `data-room-intel serve [--port N]` | Runs the API and the web app on 127.0.0.1 (default port 8000) |

`DIR` defaults to `DATA_ROOM_PATH` and `ID` to `DATA_ROOM_ASSET_ID` (the sample project).
Snapshots are deterministic: the snapshot ID hashes the file manifest, the base catalog, the
project's model extension and the pipeline version, and a rebuild produces byte-identical
tables. Projects live under `DRI_DATA_ROOT` (default `.dri-data/`, git-ignored):

```text
.dri-data/rooms/<project>/
├── project.json            name, description, source folder, template
├── source/ or <folder>     the original files (for projects created in the app, under source/)
├── incoming/               files added in the app
├── catalog/                the project's model extension, change log and proposals
├── reviews/                issue and mapping decisions (append-only)
└── snapshots/<id>/         bronze (originals), silver (extracted), gold (the graph)
```

---

## 6. Settings

| Variable | Default | Purpose |
|---|---|---|
| `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL`, `FOUNDRY_VISION_MODEL` | — | Azure AI Foundry project and model deployments (chat, mapping and naming proposals, chart reading) |
| `DOC_INTELLIGENCE_ENDPOINT` | — | Azure Document Intelligence (PDF layout and figures) |
| `AZURE_CLI_SUBSCRIPTION` | — | Pin the Azure CLI subscription when its default tenant differs from the resources'; leave empty in Azure to use managed identity |
| `DRI_DATA_ROOT` | `.dri-data/` | Projects, snapshots, decisions and caches |
| `DRI_OFFLINE` | unset | `1` uses the seeded extraction cache and the keyword router; no Azure calls |
| `DATA_ROOM_PATH` | `data/sample-room` | Folder of the sample project (relative paths are repository-relative) |
| `DATA_ROOM_ASSET_ID` | `lone-star-basin` | ID of the sample project, the default when a request names no project |
| `DRI_API_URL` | `http://127.0.0.1:8000` | Dev server only: where Vite forwards `/api` |

Authentication is Microsoft Entra ID only (`DefaultAzureCredential`); the checked-in
`.env.example` documents every variable and contains no credentials. Your identity needs
"Azure AI User" on the Foundry project and "Cognitive Services User" on the Document
Intelligence resource.

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| The browser shows the old four-view app | Hard-reload (Cmd/Ctrl+Shift+R); the browser cached the previous bundle |
| `address already in use` | Another process has the port; start with `--port` and a free port |
| `{"detail":"Not Found"}` at the page root | `frontend/dist` was missing at startup: run `npm run build` in `frontend/`, then restart `serve` |
| "This project has no data yet" / 503 `No snapshot built yet` | Expected for a new project: add files on the Data step. For the sample project, run `data-room-intel snapshot` with the same `DRI_DATA_ROOT` |
| An upload is refused (400) | Only `.xlsx`, `.xlsm`, `.csv`, `.pdf` and `.zip` are accepted, 200 MB at most; inside a zip, `.pptx` and images are skipped |
| A file went through the wrong recipe, or a table has the wrong header row | Rename the file so it no longer matches a recipe name (see Step 0) and upload it again |
| A model change names things oddly | Edit the names before approving; offline, names come from headers, online the model drafts them |
| The chat header shows "offline router" | `DRI_OFFLINE=1` is set or `.env` lacks the Foundry settings; run `data-room-intel doctor` |
| Files added with `curl` do not appear in the app | Reload the page; the app caches project data until it makes a change itself |
| `npm ci` reports an unsupported engine | Upgrade Node.js to 20.19+ or 22.12+ |

---

## 8. Developing

**Tests**: `.venv/bin/python -m pytest -q` (51 tests; the API and project tests build the
sample room offline into a temporary folder). CI runs them on Linux and macOS, builds an
offline snapshot and type-checks and builds the frontend.

**Hot reload**: run the API and the Vite dev server in two terminals:

```bash
data-room-intel serve --port 8765                              # terminal 1
cd frontend && DRI_API_URL=http://127.0.0.1:8765 npm run dev   # terminal 2 (PowerShell: $env:DRI_API_URL="http://127.0.0.1:8765"; npm run dev)
```

Open http://localhost:5173; edits under `frontend/src` appear immediately. Run `npm run
build` before committing.

**Agent Inspector**: press `F5` in VS Code and select *Debug Local Agent/Workflow HTTP
Server*. The tasks start the Agent Framework DevUI on port 8088 with the ontology workflow
and open Foundry Toolkit Agent Inspector, where you can run a snapshot and watch each step.

**Where things live**: `src/data_room_intelligence/ingest/` (discovery, tabular, GIS and PDF
extraction), `ontology/` (catalog layering, build recipes, generic mapping recipe, concept
discovery, rules, snapshot store, diff, projects), `service/` (API, named operations,
chat), `frontend/src/views/` (one file per step), `ontology/*.yaml` (the governed base
model, header rules, rules and alias tables), `docs/catalog/` (generated review artifacts;
regenerate with `catalog export`).

**Earlier pipeline**: the first version of this repository built a canonical model,
standard answers and an insight report. That code is kept at the `legacy-pipeline` tag.
