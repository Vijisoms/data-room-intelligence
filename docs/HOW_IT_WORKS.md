# How Data Room Intelligence Works

This document explains each part of the platform: the snapshot workflow, the ontology,
normalization, field mapping for new datasets, reconciliation rules, document claims,
review and publishing, and the chat. Every example comes from the sample room in
`data/sample-room` (the synthetic "Lone Star Basin" asset). For setup and commands, see the
[README](../README.md#ontology-platform-snapshots-review-chat-and-ui).

Contents

1. [The problem and the approach](#1-the-problem-and-the-approach)
2. [Design principles](#2-design-principles)
3. [The snapshot workflow](#3-the-snapshot-workflow)
4. [The ontology](#4-the-ontology)
5. [Normalization](#5-normalization)
6. [Field mapping and new datasets](#6-field-mapping-and-new-datasets)
7. [Reconciliation rules and issues](#7-reconciliation-rules-and-issues)
8. [Document claims and charts](#8-document-claims-and-charts)
9. [Review and publishing](#9-review-and-publishing)
10. [Questions and answers: named operations and the chat](#10-questions-and-answers-named-operations-and-the-chat)
11. [The web UI](#11-the-web-ui)
12. [API reference](#12-api-reference)
13. [Current limits](#13-current-limits)

---

## 1. The problem and the approach

A seller's data room describes one asset across many files that were never designed to
work together. The sample room has four workbooks, two PDF decks and four map layers:

| File | What it holds |
|---|---|
| Unit Details (xlsx) | 90 drilling units, ownership and location counts for 15 zones |
| ComboCurve Oneline (xlsx) | 640 economic locations with economics, plus a 52-month cash flow |
| LOS (xlsx) | Lease operating statements by month |
| Basis Report (xlsx) | Pricing differentials for 38 facilities |
| Asset Overview and Development Model (pdf) | Headline numbers and charts |
| Units, PDP laterals, leasehold tracts (shapefiles) | Unit polygons, 320 well laterals, 360 tracts |

The files disagree, and they identify the same things in different ways:

- ComboCurve assigns a well to one unit, but the well's lateral on the map lies in another
  unit. This happens for 317 of 320 producing wells.
- Two ComboCurve columns are both named "10% Discount Cash Flow (M$)" and differ for all
  640 locations, so "PV-10" has two answers.
- The unit shapefile's working interest differs from the Unit Details workbook for every
  unit and zone.
- Excel stores API numbers as numbers, while the map stores them as text. Unit names appear
  as `GOLDEN_CROSSING_WEST_` in one file and `GOLDEN CROSSING WEST` in another.
- The deck says "Avg Working Interest 51.1%"; the economics give 49.06%.

The platform turns the room into a **reviewed, cited knowledge graph**:

```text
 files ──▶ Bronze ──▶ Silver ──────────────▶ Gold ────────────────▶ Review ──▶ Publish
           exact      extracted values,      entities, links,       decisions  gate on open
           copies     schemas, documents,    facts, geometry,       with       blocking
           + hashes   each with its source   issues (both values    reasons    issues
                      cell, page or feature  kept, conflicts flagged)
                                                    │
                                                    ▼
                                    API ─▶ web UI and chat (answers cite sources)
```

## 2. Design principles

1. **Every value keeps its source.** Each entity, link and fact records its file and an
   exact locator: a cell (`ONELINE!KY2`), a cell range, a map feature (`feature 0`) or a
   PDF page. The UI opens any citation at that place.
2. **Competing values are kept, not overwritten.** When two sources disagree, both values
   stay in the graph and a rule raises an issue. A reviewer decides; the pipeline never
   picks a winner silently.
3. **Deterministic IDs and snapshots.** Entity IDs come from keys (`well:42901144110000`),
   and the snapshot ID is a hash of the inputs. Rebuilding the same inputs gives the same
   snapshot ID and byte-identical tables.
4. **The catalog is data.** Entity types, link types, measures, rules, header rules and
   alias tables are versioned YAML files in `ontology/`. Changing them changes the snapshot
   ID, so every answer can be traced to the catalog version that produced it.
5. **Models have narrow jobs.** A vision model reads charts, a chat model proposes field
   mappings and routes questions to named operations. Models never compute reported
   numbers or write queries. Model outputs are cached, so builds can be replayed offline.
6. **People approve what matters.** Field mappings proposed by overlap or a model need
   approval, and blocking issues hold publishing until someone decides them.
7. **Files first.** Storage is Parquet plus an embedded DuckDB database under
   `DRI_DATA_ROOT`, so the whole system runs on a laptop. A hosted version can move the same
   tables to a lake and a database without changing the model.

## 3. The snapshot workflow

`data-room-intel snapshot` runs a Microsoft Agent Framework workflow
(`src/data_room_intelligence/ontology/workflow.py`):

```text
                 BuildRequest(room_id, room_dir)
                              │
                       ┌──────▼──────┐
                       │  Discover   │  manifest, snapshot ID, Bronze copies
                       └──────┬──────┘
             fan-out ┌────────┼─────────┐
              ┌──────▼───┐ ┌──▼───────┐ ┌▼─────────┐
              │ GIS      │ │ Tabular  │ │ PDF      │   run in parallel; each writes Silver
              └──────┬───┘ └──┬───────┘ └┬─────────┘
              fan-in └────────┼──────────┘
                     ┌────────▼────────┐
                     │ BuildOntology   │  mappings, Gold build, rules, issues
                     └────────┬────────┘
                    blocking issues open?
                 no ──────────┴────────── yes
                 │                         │
           status "ready"         review gate: the workflow pauses with a
                                  ReviewRequest; "hold" leaves the snapshot
                                  "in_review", "publish" needs reviewer + reason
```

The workflow writes checkpoints to `DRI_DATA_ROOT/checkpoints`. The CLI answers the review
request with "hold" automatically. The same workflow appears in the Agent Framework DevUI
(`debug_server.py`), where you can watch each executor run.

### 3.1 Discover

- **Sources**: every file under the room folder plus uploaded files in
  `rooms/<room>/incoming/`. Hidden files and Office lock files (`~$*.xlsx`) are skipped.
- **Roles**: file names are matched to roles, for example `unit details` →
  `unit_details` (file ID `unit-details`), `combocurve` → `economics_oneline`, `pdp` →
  `gis_pdp_laterals`. Unknown files get a file ID from their name, such as
  `seller-well-production-2026-07`.
- **Protection**: rights-managed (encrypted) workbooks are detected, recorded in the
  manifest and skipped by the tabular track instead of being read as garbage.
- **Manifest**: path, size, SHA-256, kind, role and shapefile bundle for every file.
- **Snapshot ID**: `"s-" + sha256(manifest digest | catalog fingerprint | "pipeline-0.1")[:12]`.
  The catalog fingerprint hashes every YAML file in `ontology/`. Uploading a file, changing
  a header rule or bumping the pipeline version therefore produces a new snapshot ID.
- **Bronze**: byte-identical copies of the originals.

### 3.2 GIS track

- Reads each shapefile bundle and takes the coordinate system from its `.prj` (all sample
  layers are EPSG:4326).
- Computes geodesic area (acres) and length (feet) on the WGS84 ellipsoid.
- Finds spatial link candidates with a spatial index:

  | Candidate | Test | Sample count |
  |---|---|---|
  | `lateral_in_unit` | the whole lateral is covered by the unit polygon | 320 |
  | `lateral_crosses_tract` | the lateral intersects the tract (crossing length kept) | 790 |
  | `tract_within_unit` | the tract polygon is covered by the unit polygon | 360 |
  | `same_geometry` | a polygon in the August unit layer equals one in the September layer | 90 |

- Writes `features.parquet`, `spatial_candidates.parquet` and one GeoJSON file per layer
  for the map view.

### 3.3 Tabular track

Workbooks are read natively with openpyxl (no Excel needed). Known layouts have extractors
("families"); everything else goes through generic table detection.

| Family | Layout handled |
|---|---|
| Unit Details | Three header rows (5 to 7) with merged block titles; data rows 8 to 97 keyed by unit name in column C |
| ComboCurve ONELINE | One header row, 370 columns, one row per economic location |
| ComboCurve CASHFLOW | Monthly totals for all wells |
| LOS | Line items in column A, months across columns, sections such as "Revenue" |
| Basis Report | Previous-month and forward-12-month sections per facility, plus a strip-price table |
| Generic | Header row detection: the first row where at least 60% of filled cells are text and the next row has data |

Every data cell becomes a **staged value**: `dataset_id, record_key, row, column, field_id, num,
text, quality`. A formula cell whose saved result is missing gets `quality =
"uncached_formula"` and no value. It is never read as zero (the LOS file has 1,165 such
cells).

Each dataset is also **profiled** into a schema: inferred type, unit (from header text such
as `(M$)`), scale, null rate, distinct count, samples and whether the column could be a key.

### 3.4 PDF track

1. **Layout**: Azure AI Document Intelligence `prebuilt-layout` returns pages, text lines,
   paragraphs with roles, tables and figure regions. Results are cached by the file's
   SHA-256. Offline, without a cache, plain text extraction is used instead.
2. **Page images** are rendered at 96 dpi for the viewer.
3. **Figures** are cropped at 144 dpi from the page. For charts with 45-degree axis labels,
   Document Intelligence returned rotated or off-page regions, so the crop falls back to the
   whole page and records that.
4. **Charts** are read by a vision model (gpt-5.4) with structured output: chart type,
   title, unit and series of (x, y) points. Results are cached by the file hash, figure,
   crop type and prompt version.
5. **Claims**: headline numbers are extracted from the paragraphs (see
   [section 8](#8-document-claims-and-charts)).

### 3.5 Build, rules and storage

`BuildOntology` collects the three tracks, builds the Gold tables
(`ontology/build.py`), proposes and applies field mappings (`ontology/mapping.py`),
evaluates the rules (`ontology/rules.py`) and writes:

```text
.dri-data/rooms/lone-star-basin/
├── incoming/                      uploaded datasets (part of the next snapshot)
├── reviews/
│   ├── decisions.jsonl            issue decisions (append-only)
│   └── mapping-decisions.jsonl    field mapping decisions (append-only)
├── latest.json                    pointer to the newest snapshot
└── snapshots/s-1bcedfa0afa5/
    ├── bronze/                    originals/ + manifest.json
    ├── silver/                    schemas/, gis/, tabular/, documents/, mappings.json, summary.json
    └── gold/                      nodes, edges, facts, aliases, geometries, issues (.parquet)
                                   ontology.duckdb (the same tables in one file, for SQL)
                                   snapshot.json (status, versions, counts, build time)
```

The sample room produces 1,596 entities, 4,928 links, 38,463 facts, 770 geometries and
2,984 issues (2,307 blocking). After the uploaded production file is approved, facts rise
to 39,423.

## 4. The ontology

### 4.1 The catalog

`ontology/catalog.yaml` (version 0.1.0, a draft for XOM review) defines what can exist.
`data-room-intel catalog export` renders it as a data dictionary, a Mermaid diagram, a JSON
Schema and an RDF/Turtle file in `docs/catalog/`. A test keeps those files in sync.

**Entity types** (ID = `<prefix>:<key>`):

| Type | ID prefix | Key | Sample count |
|---|---|---|---|
| Asset | `asset` | name | 1 |
| Unit | `unit` | name | 90 |
| Zone | `zone` | code | 15 |
| Well | `well` | api_14 | 320 |
| EconomicLocation | `location` | inpt_id | 640 |
| EconomicCase | `case` | project | 1 |
| LeaseholdTract | `tract` | geometry_hash | 360 |
| Operator | `operator` | name | 2 |
| County | `county` | name | 8 |
| DevelopmentArea | `devarea` | name | 6 |
| BatteryCode | `battery` | code | 92 |
| PricingFacility | `facility` | name | 38 |
| ReportingScope | `scope` | name | 5 |
| DocumentClaim | `claim` | claim_id | 18 |

A Well (a drilled lateral on the map) and an EconomicLocation (a row in the economics) are
separate types: 320 locations have no well yet (undeveloped, DUC, permit, drilling).

**Relationship types** and how each is built:

| Link | From → to | Method | Build rule | Count |
|---|---|---|---|---|
| IS_WELL | EconomicLocation → Well | key | ComboCurve API 14 equals PDP API_14, both as 14-digit text | 320 |
| ASSIGNED_TO_UNIT | EconomicLocation → Unit | source | ComboCurve UNIT after name normalization | 640 |
| LATERAL_IN_UNIT | Well → Unit | spatial | Lateral covered by the unit polygon | 320 |
| CROSSES_TRACT | Well → LeaseholdTract | spatial | Lateral intersects the tract | 790 |
| WITHIN_UNIT | LeaseholdTract → Unit | spatial | Tract covered by the unit polygon | 360 |
| TARGETS_ZONE | EconomicLocation → Zone | alias | Landing zone through the `landing_zones` alias table | 578 |
| VALUED_IN | EconomicLocation → EconomicCase | source | Project name and qualifiers | 640 |
| OPERATED_BY | EconomicLocation → Operator | source | Current Operator; the operator alias stays on the link | 640 |
| SOLD_THROUGH | EconomicLocation → BatteryCode | source | BATTERY column | 347 |
| PRICED_AT | BatteryCode → PricingFacility | crosswalk | Customer-supplied crosswalk (none supplied) | 0 |
| IN_COUNTY | Unit → County | source | Unit Details County | 90 |
| IN_DEV_AREA | Unit → DevelopmentArea | source | Unit Details Development Area | 90 |
| PART_OF | Unit → Asset | source | Room inventory | 90 |
| REPORTS_ON | ReportingScope → Asset | source | Room inventory | 5 |
| ABOUT | DocumentClaim → Asset | document | Claim extracted from a room document | 18 |

The **method** tells you how much to trust a link: `key` means exact identifier equality,
`spatial` comes from geometry, `alias` depends on an alias table that still needs approval,
`source` is stated by one file, `document` comes from a PDF and `crosswalk` needs a mapping
table from the customer. PRICED_AT has no links because no crosswalk was supplied, and the
schema graph shows it as a dashed red gap.

**Measures** (27) are numeric facts with a unit and dimensions. For example, `Unit.net_acres`
(acres, by zone), `EconomicLocation.dcf10_ky` (M$), `ReportingScope.los_value` (by month and
line item), `PricingFacility.basis_value` and `Well.oil_bbl` (bbl, by month).

### 4.2 Gold tables

| Table | One row per | Key columns |
|---|---|---|
| nodes | entity | id, type, key, label, file, locator, props (JSON) |
| edges | link | id, source, kind, target, method, file, locator, props |
| facts | measured value | subject, measure, value, unit, zone, period, item, section, case_id, dataset_id, file, locator, quality |
| aliases | alternative name | entity, alias, source |
| geometries | shape | entity, kind, wkb, geodesic_acres, length_ft, file, locator |
| issues | rule finding | issue_id, rule, severity, subject, qualifier, detail, blocks, assertions |

Properties describe an entity (a well's name, a unit's gross acres). Facts are measured
values that need dimensions: a unit's net acres are different for each of 15 zones, and LOS
values differ by month and line item. Keeping facts in one long table makes every number
traceable to one cell and lets the same measure come from different files.

### 4.3 Example: one well and its neighborhood

The economic location `location:INPT8CiDhiY7Et` is row 2 of ComboCurve ONELINE:

```text
EconomicLocation  JARDINE 4-27 A 4LS        (ONELINE!C2)   status PRODUCING, landing zone MID SPRB SHALE
 ├─ IS_WELL           key      ONELINE!B2   → Well 42901144110000 (PDP feature 0)
 ├─ ASSIGNED_TO_UNIT  source   ONELINE!IO2  → Unit BADGER DRAW            source value "BADGER_DRAW_"
 ├─ OPERATED_BY       source   ONELINE!M2   → Operator LONE STAR BASIN OPERATING LLC   alias "NON-OP"
 ├─ TARGETS_ZONE      alias    ONELINE!CC2  → Zone MSS                     alias table status: proposed
 ├─ SOLD_THROUGH      source   ONELINE!IL2  → BatteryCode BATTERY32
 ├─ VALUED_IN         source   ONELINE!FL2  → EconomicCase
 └─ facts: wi 0.194 (JP2), nri 0.150 (JQ2), irr 0.442 (LR2), dcf10_ky 6,816.98 M$ (KY2), dcf10_mf 5,935.99 M$ (MF2)

Well 42901144110000
 ├─ LATERAL_IN_UNIT   spatial  "feature 0 covered by unit feature 36" → Unit GOLDEN CROSSING WEST
 ├─ CROSSES_TRACT     spatial  (one link per leasehold tract crossed, with crossing length)
 └─ facts from the uploaded seller file: oil_bbl, gas_mcf, water_bbl, days_on by month
```

The two unit links disagree (BADGER DRAW versus GOLDEN CROSSING WEST), so both stay and
`UNIT_ASSIGNMENT_CONFLICT` flags the well. The Explore view draws both links in red.

## 5. Normalization

Normalization makes identifiers comparable without changing the source values. Original
spellings are kept as aliases, and nothing is fuzzy-matched.

| What | Rule | Example |
|---|---|---|
| API numbers | Digits only; Excel numbers lose the `.0`; 10, 12 or 14 digits are padded to 14-digit text | `42901144110000.0` (Excel) and `42-901-14411-0000` (seller file) both become `42901144110000`. API-10 `4290114411` is kept as an alias |
| Unit names | Uppercase, underscores to spaces, collapse spaces; the ID uses a slug | `GOLDEN_CROSSING_WEST_` → `GOLDEN CROSSING WEST` → `unit:golden-crossing-west`; the original spellings are searchable aliases |
| Headers | Lowercase, punctuation to spaces (the header key); a repeated header gets `.1` | `10% Discount Cash Flow (M$)` → `10 discount cash flow m` (column KY); the second one → `10 discount cash flow m 1` (column MF) |
| Percent columns | Profiling labels the scale from the values: a maximum of 1.5 or less is a fraction, larger is percent points. Mappings convert to fractions | `WI Oil (%)` holds `0.194` and is stored as is; `IRR (%)` holds percent points (`44.2`), so its mapping divides by 100 → 0.442 |
| Money | `(M$)` means thousand dollars | `6,816.98 M$` = $6.82 million |
| Units of measure | Taken from the parentheses at the end of a header | `Net Oil Sales Volume (MBBL)` → unit `MBBL` |
| Zones (economics) | `landing_zones` alias table (status: proposed) | `WOLFCAMP A` → `WCA`; `MID SPRB SHALE` → `MSS`; `LWR SPRB SAND` → no bench, which raises `ZONE_ALIAS_MISSING` (62 locations) |
| Zones (map fields) | `gis_zone_fields` alias table | `WI_MISS` → zone `MSS` (a misspelling), `WI_WCB1` → `WCB I`, `WI_STBND` → `STR / BND` |
| Operators | Name to a slug ID; the alias column stays on the link | Operator `LONE STAR BASIN OPERATING LLC` with alias `NON-OP` on 483 links |
| Dates | ISO date text, first 10 characters | `2026-06-01` |
| Coordinates | Coordinate system from the `.prj`; geodesic measures on WGS84 | GOLDEN CROSSING WEST: 953.51 contractual gross acres (workbook) and 1,150 mapped acres (polygon); both are kept |
| Entities without IDs | Leasehold tracts have no source ID, so the ID is a hash of the geometry | `tract:` + first 12 hex characters of `sha256(WKB)` |
| Missing formula results | Flagged, value left empty, never zero | 1,165 LOS cells → `FORMULA_CACHE_MISSING` issues |

## 6. Field mapping and new datasets

A field mapping links a source column to a catalog target: `Type.property`,
`Type.measure`, a key, a dimension (such as `Well.month`) or a link. The known families
(Unit Details, ComboCurve, LOS, Basis) are turned into the ontology by built-in recipes in
`ontology/build.py`; header rules still label their columns so the Inputs view can show
what each column feeds. Any other table, such as a new upload, goes through three proposal
tiers:

1. **Header rules** (`ontology/header_rules.yaml`): approved regular expressions on the
   header key. For example, `^api 14$` → `Well.api_14` (key), or
   `^(prod|production|report) ?(month|date|period)$|^month$` → the month dimension.
   Matches are approved automatically.
2. **Value overlap**: for each unmapped column, normalized values are compared with
   existing entity keys (`Well.api_14`, `Well.api_10`, `EconomicLocation.inpt_id`,
   `Unit.name`). If at least half match, the column is proposed as that key, with the match
   rate.
3. **Model proposals**: once the key tells us what the rows describe (for example
   `Well`), the remaining columns, with sample values, are sent to gpt-5.4-mini. The prompt
   lists only the targets the catalog allows for that type, and the model returns structured
   output: target, confidence and a one-sentence rationale. Answers are cached. Offline, a
   keyword heuristic proposes the same targets for oil, gas, water and days columns.

Proposals other than header rules wait for approval. Decisions are stored by header key and
target, so the next file with the same headers is mapped without another review. On the
next rebuild, approved key and measure mappings become facts on the matched entities, each
citing its cell.

### Example: the seller production file

`data/scenarios/new-dataset/Seller Well Production_2026.07.xlsx` has a sheet "Monthly
Production" with 42 wells × 6 months. Two of the wells do not exist in the room. After
upload, the proposals are:

| Column | Header | Proposed target | How | Confidence | Rationale |
|---|---|---|---|---|---|
| A | API Number | `Well.api_14` (key) | value overlap | 0.952 (240/252) | 240 of 252 values match existing `Well.api_14` after normalization |
| B | Lease / Well Name | `Well.well_name` | model | 0.99 | Header and repeated well-style values identify the well name |
| C | Production Month | `Well.month` (dimension) | header rule | 1.0 | `header rule /^(prod\|production\|report) ?(month\|date\|period)$\|^month$/` |
| D | Oil Volume | `Well.oil_bbl` | model | 0.99 | Monthly oil production in barrels |
| E | Gas Volume | `Well.gas_mcf` | model | 0.99 | Monthly gas production in mcf |
| F | Water Volume | `Well.water_bbl` | model | 0.99 | Monthly water production in barrels |
| G | Days Producing | `Well.days_on` | model | 0.99 | Producing days in the month |

After a reviewer approves A and D to G and rebuilds:

- 960 facts (40 wells × 6 months × 4 measures) attach to existing wells. For example,
  JARDINE 4-27 A 4LS oil for January 2026 cites `Monthly Production!D2`.
- The 12 rows for `42-901-99998-0000` and `42-901-99999-0000` match no well, so one
  `UNMATCHED_KEY` issue lists them instead of dropping them silently.
- The chat can now answer "What did JARDINE 4-27 A 4LS produce in June 2026?" with 6,578 bbl
  oil, 25,406 mcf gas and 7,842 bbl water, citing the seller file.

## 7. Reconciliation rules and issues

Rules live in `ontology/rules.yaml`. Each issue has a deterministic ID,
`issue:<rule>:<subject>[:<qualifier>]`, so the same conflict has the same ID in every
rebuild and a recorded decision keeps applying. Each issue carries two **assertions**: the
competing values with their file and locator.

| Rule | Severity | Check | Blocks | Sample |
|---|---|---|---|---|
| UNIT_ASSIGNMENT_CONFLICT | blocking | ComboCurve unit differs from the unit containing the lateral | Unit-level economics totals | 317 |
| OWNERSHIP_VALUE_CONFLICT | blocking | Shapefile WI differs from Unit Details operational WI for a zone | WI and NRI answers | 1,350 |
| VALUE_FIELD_CONFLICT | blocking | ONELINE KY and MF share a header and differ | PV-10 answers | 640 |
| ZONE_ALIAS_MISSING | warning | Landing zone has no approved bench | Zone totals | 62 |
| OPERATOR_ALIAS_CONFLICT | warning | Seller-operated location carries the alias NON-OP | Operated versus non-operated split | 483 |
| CLAIM_MISMATCH | warning | A document number differs from the room | Nothing | 2 |
| UNMATCHED_KEY | warning | A mapped key in a new dataset matches no entity | Facts from those rows | 1 |
| CROSSWALK_MISSING | info | Battery code has no pricing facility | Nothing; price answers marked unsupported | 92 |
| FORMULA_CACHE_MISSING | info | Formula cell has no saved result | Nothing; flagged, never zero | 38 |

How each rule works, with a real issue:

**UNIT_ASSIGNMENT_CONFLICT.** For every well, follow IS_WELL back to its economic location
and compare that location's ASSIGNED_TO_UNIT target with the units in the well's
LATERAL_IN_UNIT links.

```text
issue:unit-assignment-conflict:well:42901144110000
  detail: ComboCurve assigns BADGER DRAW; the lateral lies in GOLDEN CROSSING WEST
  A: ComboCurve UNIT = BADGER DRAW              ONELINE!IO2
  B: GIS lateral within unit = GOLDEN CROSSING WEST    LSB_PDP_20260904.shp, feature 0 covered by unit feature 36
```

**OWNERSHIP_VALUE_CONFLICT.** Compare `gis_wi` (shapefile) with `operational_wi` (Unit
Details) for each unit and zone, with a tolerance of 0.000001. All 90 × 15 pairs differ.

```text
issue:ownership-value-conflict:unit:desert-basin-east:uss
  detail: USS: GIS WI 0.6580 vs Unit Details 0.6671
  A: Unit Details operational WI = 0.66713      Unit Details!CM8
  B: Unit shapefile WI = 0.658026               LSB_UNITS_20260806.shp, feature 0 WI_USS
```

**VALUE_FIELD_CONFLICT.** Compare `dcf10_ky` with `dcf10_mf` for each location.

```text
issue:value-field-conflict:location:INPT8CiDhiY7Et
  detail: 10% discount cash flow KY 6,817.0 vs MF 5,936.0 (M$)
  A: ONELINE KY = 6816.976    ONELINE!KY2
  B: ONELINE MF = 5935.99     ONELINE!MF2
```

**ZONE_ALIAS_MISSING**: a location with no TARGETS_ZONE link, for example the location in
ONELINE row 25, whose landing zone is `LWR SPRB SAND`. **OPERATOR_ALIAS_CONFLICT**: the
operator is the seller but the alias column says `NON-OP` (`ONELINE!M2`).
**CROSSWALK_MISSING**: `BATTERY32` has no PRICED_AT link. **FORMULA_CACHE_MISSING**: one
issue per LOS line item, for example "REVENUE WITH DEDUCTS: OIL: 55 monthly formulas have
no saved value (2022-01-01 to 2026-07-01)" at `LSBIV NET!C93`.

## 8. Document claims and charts

### 8.1 Extracting claims

Decks show headline numbers as KPI cards. From the layout paragraphs, the extractor:

1. Skips page headers, footers, titles and any text inside a figure region.
2. Matches `Label Value[unit]` in one paragraph (`Drilling Units 90`,
   `Avg Working Interest 51.1%`, `D&C Capital ($MM) $8.4`), or a value-only paragraph with a
   label directly above it (within 0.8 inch and overlapping horizontally).
3. Ignores dates: a label ending in a month or quarter with a value between 1900 and 2100
   ("June 2026").
4. Creates a DocumentClaim with a stable ID, `<file>-p<page>-<label slug>`, for example
   `asset-overview-p2-avg-working-interest`.

The sample decks yield 18 claims: 10 from the Asset Overview, 8 from the Development Model.

### 8.2 Checking claims

The rules compute the same metric from the room and compare it within the precision the
deck printed: tolerance = 0.5 × 10^(−decimals). "51.1%" allows ±0.05, "70,440" allows ±0.5
and "75%" allows ±0.5.

| Claim (Asset Overview, page 2) | Computed from the room | Result |
|---|---|---|
| Drilling Units 90 | 90 Unit Details rows | match |
| Primary-Bench Net Acres 38,664 | 38,663.82 (WCA net acres, `Unit Details!P8:P97`) | match |
| Total Econ Locations 640 | 640 ONELINE rows | match |
| Counties 8 | 8 | match |
| Development Areas 6 | 6 | match |
| Gross Acres 70,440 | 70,440.39 (`Unit Details!H8:H97`) | match |
| Producing Wells (PDP) 320 | 320 laterals | match |
| Operated % 75% | 75.47 (share operated by the seller) | match |
| Avg Working Interest 51.1% | 49.06 (mean WI, `ONELINE!JP2:JP641`) | **mismatch** |
| Avg Net Revenue Interest 37.8% | 37.74 (mean NRI, `ONELINE!JQ2:JQ641`) | **mismatch** (off by 0.06, more than ±0.05) |

The two mismatches become CLAIM_MISMATCH issues. The 8 Development Model claims (PV-10
$6.1 MM, IRR 68%, EUR 1,650 MBOE, IP30, payout, breakeven, D&C capital, oil cut) are
"unverifiable" because the room has no type-curve data to compute them from.

Note that "Operated % 75%" matches only when you count by operator name. Every one of those
483 locations also carries the alias NON-OP, which is why OPERATOR_ALIAS_CONFLICT exists.

### 8.3 Charts

The vision model's chart readings are marked approximate and never override workbook
facts. They are used for cross-checks. The ownership chart (Asset Overview page 4, figure
4.1) plots working interest by zone. The `claim_check` operation compares each bar with the
mean Unit Details operational WI for that zone: 13 of 15 zones agree within 0.5 points, and
the larger differences are MSSP and WDFD. The Inputs view shows this table next to the crop
that was sent to the model.

## 9. Review and publishing

### 9.1 Issue decisions

In the Review view, a reviewer picks an option (for VALUE_FIELD_CONFLICT: "KY is PV-10",
"MF is PV-10", "Ask seller", "Defer") or types one, and must give a reason. The scope is one
issue or the whole rule. Each decision is appended to `reviews/decisions.jsonl`. A record
looks like this (illustrative values):

```json
{"decision_id": "decision:3f2c9a1b7d4e", "issue_id": "issue:value-field-conflict:location:INPT8CiDhiY7Et",
 "rule": "VALUE_FIELD_CONFLICT", "scope": "issue", "choice": "KY is PV-10",
 "reason": "<why this choice is right>", "reviewer": "<reviewer name>",
 "snapshot_id": "s-1bcedfa0afa5", "decided_at": "2026-10-15T18:05:12+00:00"}
```

When a snapshot loads, decisions are matched by issue ID, then by rule, and matching issues
become "decided". Because issue IDs are deterministic, decisions keep applying to later
snapshots. The log is never edited, so it doubles as an audit trail. Both source values
always stay in the graph.

### 9.2 Mapping decisions

Approving or rejecting a field mapping appends to `reviews/mapping-decisions.jsonl` with the
header key, target, reviewer and time. The next rebuild uses it, and future files with the
same header reuse it.

### 9.3 The publish gate

A snapshot is "in_review" while any blocking issue is open, otherwise "ready".
`data-room-intel publish-snapshot` (or **Publish snapshot** in Review) refuses while
blocking issues are open. The sample room has 2,307 (317 + 1,350 + 640). An override needs
`--force` with a reviewer and a reason, which are written into `snapshot.json` with the
number of open blocking issues at the time.

## 10. Questions and answers: named operations and the chat

Answers come from nine **named operations** (`service/operations.py`). Each returns data, a
one-paragraph summary, citations and UI actions:

| Operation | Input | Returns |
|---|---|---|
| room_overview | none | Counts of files, entities, links, facts and open issues |
| zone_summary | bench code or name | Net acres, net locations (10K equivalents × WI), locations by status with both 10% value columns |
| unit_profile | unit name | County, development area, acreage, assigned locations, laterals, tracts, ownership conflicts |
| well_profile | API, well name or INPT ID | Status, zone, both unit assignments, economics, monthly production, issues |
| locations | zone, status, unit | Matching economic locations with value totals |
| conflicts | rule or entity | Open issues by rule with severity and what each blocks |
| claim_check | document | Claims versus computed values, plus chart cross-checks |
| gap_report | none | Missing crosswalk, unmapped zones, uncached formulas, pending mappings, unmatched keys |
| lineage | entity | Every file, cell, page or feature behind an entity, its links and facts |

### 10.1 How a question is answered

```text
question ─▶ chat agent (gpt-5.4-mini, Agent Framework) whose only tools are the 9 operations
               │ calls one operation (two if needed)
               ▼
         operation result (data, summary, citations, actions)
               │
         model writes a short answer from the result
               │
         verification: every number in the answer must appear in the operation
         result (formatting and rounding of the same figure allowed)
               │ fails → the operation's own summary is shown instead
               ▼
         answer + operation trace + citations + actions
```

Without a model (offline, or if the call fails), a keyword router picks the same operations
and shows their summaries. The verification step caught a real problem during development:
before `well_profile` returned production data, the model filled in production numbers it
had not been given. The answer was replaced automatically, and the fix was to give the
operation the data.

### 10.2 Examples

The first quote in each example is the operation's own summary (what offline mode shows);
the others are answers from gpt-5.4-mini in a live run.

**"What are the Wolfcamp A net acres, net locations and PV-10?"** → `zone_summary(zone="WCA")`

> Wolfcamp A (WCA): 38,663.82 net acres and 96.98 net locations (10,000-ft equivalents x
> operational WI) from Unit Details; 70 economic locations target this bench. PV-10 is not
> resolved: both '10% Discount Cash Flow' columns are shown because 70 locations have an
> open VALUE_FIELD_CONFLICT.

The chat panel also shows the operation's table:

| Status | Locations | KY $MM | MF $MM |
|---|---|---|---|
| PRODUCING | 32 | 343.4 | 146.6 |
| UNDEVELOPED | 19 | 188.3 | 87.7 |
| DUC | 8 | 73.7 | 44.6 |
| DRILLING | 7 | 81.0 | 40.9 |
| PERMIT | 4 | 13.1 | 22.6 |

Citations: `Unit Details!P8:P97` (net acres), `Unit Details!CR8:CR97` (WI),
`Unit Details!DX8:DX97` (locations), `ONELINE!KY2:KY641` and `ONELINE!MF2:MF641`. Actions:
show the zone on the graph, or review the PV-10 conflict.

**"What did JARDINE 4-27 A 4LS produce in June 2026?"** → `well_profile(well="JARDINE 4-27 A 4LS")`

> JARDINE 4-27 A 4LS produced 6,578 bbl oil, 25,406 mcf gas, and 7,842 bbl water in June
> 2026. There is an open blocking unit assignment conflict: ComboCurve assigns BADGER DRAW,
> but the lateral lies in GOLDEN CROSSING WEST. There is also an open blocking value field
> conflict on 10% discount cash flow.

The citations include the seller file's oil cell for June; clicking it opens the uploaded
workbook at that cell with its lineage.

**"Does the asset overview deck agree with the data?"** → `claim_check`

> Mostly yes, but not fully. The overview deck matches 8 of 10 headline claims. Two claims
> do not match: Avg Net Revenue Interest 37.8% versus 37.74 computed from the room, and Avg
> Working Interest 51.1% versus 49.06 computed from the room. The ownership chart on page 4
> is also only approximate: it matches Unit Details within 0.5 points for 13 of 15 zones,
> with larger differences in MSSP and WDFD.

**"What are the data gaps?"** → `gap_report`

> The main data gaps are: no crosswalk links 92 battery codes to 38 basis-report
> facilities, so price answers are unsupported; 62 locations have a landing zone with no
> approved bench; 38 LOS line items contain formulas without saved values; 8 document
> claims cannot be computed from the room; 1 field mapping awaits approval; and 1 dataset
> has unmatched keys.

## 11. The web UI

The UI (`frontend/`, React and Vite) is one workspace with a navigation rail, the working
view in the center and the chat docked on the right. A single click selects; a double click
opens the inspector drawer. The URL keeps the state, so any view can be shared as a link.

| View | What you can do |
|---|---|
| Explore | See the schema graph (types sized by count, link types with counts, data gaps dashed) or an entity's neighborhood (two hops, hubs limited to one hop, large groups capped). Search with `/`, filter by type, link method and severity. Conflicting links are red; badges count open issues. Double-click any node for its properties, relationships, facts, sources, issues and schema |
| Inputs | Browse every file. Sheets show mapped columns (green underline approved, amber proposed) and flag uncached formulas; selecting a cell shows its mapping, the facts it produced, the entities it feeds and the issues that cite it. PDFs show pages with text, figure and claim overlays, extracted chart data and cross-checks. Map layers show units, tracts and laterals, with unit conflicts in red. Upload a dataset and approve its mappings here |
| Schema | The catalog as a dictionary: entity types with properties and measures, relationship types with build rules, rules and alias tables |
| Review | Rule cards with open and decided counts, a paged issue queue, side-by-side evidence with citations (and a mini map for unit conflicts), decisions with a reason and scope, and the publish gate |
| Chat | Questions answered by named operations, with the operation trace, result tables, citations that open the cited cell, page or feature, and actions such as "Show on graph" |

## 12. API reference

The FastAPI service (`service/api.py`) serves the UI and these endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/health`, `/api/room`, `/api/rooms` | Status, snapshot metadata and counts |
| `GET /api/catalog` | Catalog with rules, alias tables and instance counts |
| `GET /api/graph/viz/schema` | Type and link counts for the schema graph |
| `GET /api/graph/viz/search?q=` | Entity search by label, ID, alias or API digits |
| `GET /api/graph/viz/neighborhood?id=&depth=&types=&methods=&issues_only=` | Capped neighborhood with conflict flags |
| `GET /api/graph/viz/interpret?id=` | Entity card: properties, links, facts, issues, geometry, schema |
| `POST /api/graph/ask` | Chat question → answer, operations, citations, actions |
| `GET /api/graph/operations`, `POST /api/graph/operations/{name}` | List or run a named operation |
| `GET /api/files`, `/api/files/{id}` | File inventory; schemas, tables, mappings, document and claim checks |
| `GET /api/files/{id}/grid?sheet=&r0=&r1=&c0=&c1=` | A window of sheet cells with formula flags |
| `GET /api/files/{id}/lineage?sheet=&cell=` | Cell value, mapping, facts, entities and issues |
| `GET /api/files/{id}/pages/{n}.png`, `/figures/{fid}.png` | Rendered pages and figure crops |
| `GET /api/layers/{file_id}` | GeoJSON with each feature's entity and issue counts |
| `GET /api/issues`, `/api/rules`; `POST /api/issues/decision` | Issue queue and decisions |
| `GET /api/mappings`; `POST /api/mappings/decision` | Mapping proposals and decisions |
| `POST /api/uploads`, `/api/rebuild`, `/api/publish` | Add a dataset (.xlsx or .csv, 20 MB), rebuild, publish |

## 13. Current limits

- A decision marks issues as decided, but answers still show both values (for example KY
  and MF). Using the chosen value in answers is a next step.
- New datasets add facts to existing entities matched by key. Creating new entities or links
  from a new file needs a catalog or recipe change.
- Price questions are unsupported until the customer supplies a battery-to-facility
  crosswalk.
- The alias tables (`landing_zones`, `gis_zone_fields`) are proposed and need approval from
  the customer's subsurface expert.
- The catalog is version 0.1.0, a draft pending XOM review.
- The server runs one room, locally, without sign-in. Hosting and authentication are the next
  milestone (M6).
