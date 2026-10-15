# Data Room Intelligence

Data Room Intelligence turns an upstream oil and gas M&A data room (workbooks, PDF
decks and map layers) into a reviewed, cited knowledge graph: an ontology of units,
wells, economic locations and their facts, with conflicts between sources flagged
for review, a chat that answers with citations, and a web UI to explore it all.
[docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) explains the design in detail.

## Sample data room (synthetic)

**The sample room contains 100% SYNTHETIC, fictional data.** It mirrors the structure,
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

### Contents (mirrors the original data room layout)

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

Row counts are representative samples (about 90 units, 640 economic locations and
320 producing wells) rather than the full asset, which is enough to convey the schema.

## Setup

### Install
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
in Azure so managed identity is used. The checked-in `.env.example` documents every
variable and contains no credentials or environment-specific endpoints.

## Ontology platform: snapshots, review, chat and UI

The ontology platform turns the room into a versioned knowledge graph that people
can explore, question and correct. [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md)
explains the workflow, ontology, normalization, field mapping, rules, document
claims, review and chat in detail, with examples from the sample room.

| Step | Command | Result |
|---|---|---|
| Check | `data-room-intel doctor` | Checks the data room, Azure identity, chat and vision models and Document Intelligence |
| Catalog | `data-room-intel catalog validate` / `catalog export --out docs/catalog` | Validates `ontology/catalog.yaml` (14 entity types, 15 relationship types, 27 measures) and renders the dictionary, Mermaid, JSON Schema and Turtle |
| Ingest | `data-room-intel ingest` | Bronze copy and manifest, then silver: GIS features and spatial candidates, staged workbook values, PDF layout, figures and claims |
| Snapshot | `data-room-intel snapshot` | Agent Framework workflow: discover, then GIS, tabular and PDF tracks in parallel, ontology build, reconciliation rules and a review gate. Writes gold tables, `ontology.duckdb` and `snapshot.json` |
| Ask | `data-room-intel ask "question"` | Answers from named operations over the latest snapshot, with citations |
| Publish | `data-room-intel publish-snapshot` | Refuses while blocking issues are open; `--force --reviewer --reason` records an override |
| Serve | `data-room-intel serve [--port 8000]` | FastAPI and the web UI on 127.0.0.1 |

Snapshots are deterministic: the snapshot ID hashes the file manifest, the catalog
and the pipeline version, and a rebuild produces byte-identical gold tables. Data
lives under `DRI_DATA_ROOT` (default `.dri-data/`, git-ignored). Competing source
values are kept side by side and raised as issues; reviewers record decisions with
a reason in an append-only log.

### Offline mode

`DRI_OFFLINE=1` uses the seeded extraction cache in `data/extraction-cache/`
(Document Intelligence layouts and chart reads) and a keyword chat router, so the
pipeline, the tests and the UI run without Azure.

### Web UI

The UI is a React and Vite app in `frontend/`. FastAPI serves the built files from
`frontend/dist`, so after one build you only need the Python server. Commands below
run from the repository root with the virtual environment active
(`source .venv/bin/activate`, or `.\.venv\Scripts\Activate.ps1` on Windows).

**Prerequisites**

- The Python setup above (`pip install -e ".[dev]"`).
- Node.js 20.19+ or 22.12+ with npm (required by Vite 8). Check with `node --version`.
- For the live chat and model-proposed field mappings: a configured `.env` and
  `az login` (see [Configure Azure](#configure-azure-keyless)). Without Azure, set
  `DRI_OFFLINE=1` for every command below; the chat then uses the keyword router.

**1. Build a snapshot**

```bash
data-room-intel snapshot            # offline: DRI_OFFLINE=1 data-room-intel snapshot
```

The server loads the latest snapshot under `DRI_DATA_ROOT` (default `.dri-data/`).
Without one, every API call returns 503 "No snapshot built yet".

**2. Build the UI**

```bash
cd frontend
npm ci
npm run build                       # type-checks, then writes frontend/dist
cd ..
```

**3. Start the server and open the UI**

```bash
data-room-intel serve --port 8765
```

Open http://127.0.0.1:8765. Use `--port` to pick any free port (the default is 8000).
Build the UI before starting the server, because the server serves `frontend/dist`
only if it exists at startup. After a later UI rebuild, reload the page; restart the
server only after Python changes. The server listens on 127.0.0.1 and has no sign-in,
so do not expose it on a network.

**Develop with hot reload**

Run the API and the Vite dev server in two terminals:

```bash
data-room-intel serve --port 8765                              # terminal 1
cd frontend && DRI_API_URL=http://127.0.0.1:8765 npm run dev   # terminal 2
```

On Windows PowerShell, set the variable first: `$env:DRI_API_URL="http://127.0.0.1:8765"; npm run dev`.
Open http://localhost:5173. Vite forwards `/api` to `DRI_API_URL` (default
`http://127.0.0.1:8000`), and edits under `frontend/src` appear immediately. Run
`npm run build` before committing; CI runs the same type-check and build.

**Settings**

| Variable | Default | Purpose |
|---|---|---|
| `DRI_DATA_ROOT` | `.dri-data/` | Snapshots, review decisions, uploads and caches |
| `DRI_OFFLINE` | unset | `1` uses the cached extraction and the keyword chat router; no Azure calls |
| `DATA_ROOM_PATH` | `data/sample-room` | Room folder that uploads and **Rebuild** use (relative paths are repository-relative) |
| `DATA_ROOM_ASSET_ID` | `lone-star-basin` | Room the server loads; must match `snapshot --room-id` |
| `DRI_API_URL` | `http://127.0.0.1:8000` | Dev server only: where Vite forwards `/api` |

The URL hash keeps the view state, so links can open a specific place, for example
`#view=inputs&fileId=combocurve&sheet=ONELINE&cell=KY2` (a cell and its lineage),
`#view=review&rule=VALUE_FIELD_CONFLICT` or `#drawer=well:42901144110000` (an
entity's inspector). Add `&theme=light` or `&chat=off` as needed.

**Troubleshooting**

| Symptom | Fix |
|---|---|
| `address already in use` | Another process has the port; start with `--port` and a free port |
| `{"detail":"Not Found"}` at the page root | `frontend/dist` was missing at startup: run `npm run build`, then restart `serve` |
| "Could not load data … 503 No snapshot built yet" | Run `data-room-intel snapshot` with the same `DRI_DATA_ROOT` and room ID |
| The chat header shows "offline router" | `DRI_OFFLINE=1` is set or `.env` lacks the Foundry settings; run `data-room-intel doctor` |
| `npm ci` reports an unsupported engine | Upgrade Node.js to 20.19+ or 22.12+ |

**Views**

| View | What it shows |
|---|---|
| Explore | Schema graph and entity neighborhoods with search (`/`), type, link and severity filters, conflict links and a quick card; double-click a node for the inspector (properties, relationships, facts, sources, issues, schema) |
| Inputs | Every file: a windowed sheet grid with mapped columns and cell lineage, PDF pages with text, figure and claim overlays and chart cross-checks, and a map of units, tracts and laterals; upload new datasets and approve field mappings |
| Schema | The catalog as a data dictionary: entity types, relationships with build rules, measures, rules and alias tables |
| Review | Reconciliation rules, the issue queue, side-by-side evidence with citations, decisions (reason required) and the publish gate |
| Chat | gpt-5.4-mini on Foundry calling named operations only. Every number in an answer must appear in an operation result; answers cite cells, pages and map features, and actions open the graph, review queue or document |

### Reusability: add a new dataset

`data/scenarios/new-dataset/Seller Well Production_2026.07.xlsx` is a seller
production export with headers the pipeline has not seen (dashed API numbers,
"Oil Volume", "Production Month"). Upload it from **Inputs → Upload dataset**, or
copy it to `.dri-data/rooms/lone-star-basin/incoming/` and rebuild:

1. Each column gets a mapping proposal: header rules first (Production Month →
   dimension), then key-value overlap (API Number → `Well.api_14`: 240 of 252
   values match existing wells after normalization), then the model for the rest
   (Oil, Gas and Water Volume and Days Producing → `Well` measures).
2. Approve the proposals and rebuild: 960 monthly production facts attach to 40
   existing wells, each citing its cell (for example `Monthly Production!D2`). The
   12 rows for two unknown wells raise `UNMATCHED_KEY` instead of being dropped.
3. Ask "What did JARDINE 4-27 A 4LS produce in June 2026?". The answer uses the new
   facts and cites the seller file.

Mapping decisions are remembered by header, so the next export with the same
headers maps without another review. To reset the demo, delete
`.dri-data/rooms/lone-star-basin/incoming` and `.../reviews`, then run
`data-room-intel snapshot`.

### Ask from the command line

```bash
data-room-intel ask "What are the Wolfcamp A net acres, net locations and PV-10?"
```

The answer comes from the same named operations as the web chat and lists its
citations. With `DRI_OFFLINE=1` it uses the keyword router instead of the model.

### Debug the workflow with Agent Inspector

Press `F5` and select `Debug Local Agent/Workflow HTTP Server`. The VS Code tasks
start the Agent Framework DevUI on port 8088 with the ontology workflow and open
Foundry Toolkit Agent Inspector, where you can run a snapshot and watch each step.

### Earlier pipeline

The first version of this repository built a canonical model, standard answers, an
insight report and a draft FIMU case file (`build`, `publish` and the hosted agent).
The ontology platform replaces it. That code is kept at the `legacy-pipeline` tag:
`git checkout legacy-pipeline`.
