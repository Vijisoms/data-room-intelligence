import asyncio
import csv
import json
from pathlib import Path

import duckdb
import pytest

from data_room_intelligence.ingest.families import extract_workbook
from data_room_intelligence.ingest.manifest import build_manifest, room_sources
from data_room_intelligence.ingest.run import ingest
from data_room_intelligence.ingest.tabular import extract_table, read_csv, read_workbook, staged_rows

ROOT = Path(__file__).parents[1]
ROOM = ROOT / "data" / "sample-room"
COMBO = ROOM / "Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx"


@pytest.fixture(scope="module")
def silver(tmp_path_factory: pytest.TempPathFactory):
    patch = pytest.MonkeyPatch()
    patch.setenv("DRI_DATA_ROOT", str(tmp_path_factory.mktemp("dri")))
    patch.setenv("DRI_OFFLINE", "1")
    ctx, summary = asyncio.run(ingest("lone-star-basin", ROOM))
    yield ctx, summary
    patch.undo()


def test_manifest_groups_bundles_and_skips_lock_files(tmp_path: Path) -> None:
    manifest = build_manifest("room", room_sources(ROOM))
    assert len(manifest.files) == 26
    assert len({entry.bundle for entry in manifest.files if entry.bundle}) == 4
    assert {entry.protection for entry in manifest.files} == {"none"}
    assert len({entry.file_id for entry in manifest.files}) == 26
    (tmp_path / "a.csv").write_text("x,y\n1,2\n")
    (tmp_path / "~$a.xlsx").write_text("lock")
    assert build_manifest("room", room_sources(tmp_path)).skipped == ["~$a.xlsx"]


def test_snapshot_id_is_deterministic(silver) -> None:
    ctx, _ = silver
    again = build_manifest("lone-star-basin", room_sources(ROOM))
    assert again.snapshot_id == build_manifest("lone-star-basin", room_sources(ROOM)).snapshot_id
    assert ctx.snapshot_id.startswith("s-")


def test_gis_track(silver) -> None:
    gis = silver[1]["tracks"]["gis"]
    assert sorted(gis["layers"].values()) == [90, 90, 320, 360]
    assert gis["invalid_geometries"] == 0
    assert gis["spatial_candidates"] == {
        "lateral_in_unit": 320,
        "lateral_crosses_tract": 790,
        "tract_within_unit": 360,
        "same_geometry": 90,
    }
    assert gis["laterals_crossing_tracts"] == 319


def test_tabular_track(silver) -> None:
    ctx, summary = silver
    assert summary["tracks"]["tabular"]["sheets"] == 19
    schemas = {item["dataset_id"]: item for item in json.loads((ctx.silver / "schemas" / "tabular.json").read_text())}
    oneline = schemas["combocurve/oneline"]
    assert oneline["record_count"] == 640
    assert "370 headers, 260 populated" in oneline["notes"]
    by_header = {field["header_path"][-1]: field for field in oneline["fields"]}
    assert by_header["WI Oil (%)"]["scale"] == "fraction (0-1)"
    assert by_header["IRR (%)"]["scale"] == "percent points"
    assert by_header["10% Discount Cash Flow (M$)"]["column_ref"] == "KY"
    assert by_header["10% Discount Cash Flow (M$).1"]["column_ref"] == "MF"
    zones_by_block: dict[str, set[str]] = {}
    for field in schemas["unit-details/unit-details"]["fields"]:
        if len(field["header_path"]) >= 2:
            zones_by_block.setdefault(field["header_path"][0], set()).add(field["header_path"][1])
    assert sum(len(zones) == 15 for zones in zones_by_block.values()) == 8
    tables = json.loads((ctx.silver / "tabular" / "tables.json").read_text())
    values = duckdb.sql(f"select * from read_parquet('{ctx.silver / 'tabular' / 'values.parquet'}')")
    los_cells = 0
    for table in (t for t in tables if t["family"] == "los"):
        months = list(table["context"]["months"])
        los_cells += duckdb.sql(
            f"select count(*) from values where dataset_id = '{table['dataset_id']}' and \"column\" in ({','.join(repr(m) for m in months)})"
        ).fetchone()[0]
    uncached = duckdb.sql("select count(*) from values where quality = 'uncached_formula'").fetchone()[0]
    assert (los_cells - uncached, uncached) == (7936, 1165)
    rows = Counter()
    for table in tables:
        key = table["context"].get("section") or table["family"]
        rows[key] += table["records"]
    assert (rows["previous_month"], rows["forward_12_months"], rows["basis_strip"]) == (119, 140, 168)


def test_pdf_track_offline_from_seed_cache(silver) -> None:
    ctx, summary = silver
    pdf = summary["tracks"]["pdf"]
    assert (pdf["pages"], pdf["figures"], pdf["charts"], pdf["claims"]) == (10, 6, 5, 18)
    document = json.loads((ctx.silver / "documents" / "asset-overview" / "document.json").read_text())
    claims = {claim["label"]: claim["value"] for claim in document["claims"]}
    assert claims["Total Econ Locations"] == 640 and claims["Avg Working Interest"] == 51.1
    ownership = next(f for f in document["figures"] if f["chart"] and "Ownership" in (f["chart"]["title"] or ""))
    assert ownership["crop"].startswith("page")
    wi = next(s for s in ownership["chart"]["series"] if s["name"].startswith("Working"))
    assert abs(wi["points"][0]["y"] - 55.1) < 1.0


def test_csv_copy_stages_identical_values(tmp_path: Path) -> None:
    grid = next(g for g in read_workbook(COMBO) if g.name == "ONELINE")
    path = tmp_path / "oneline.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for row in grid.values[:41]:
            writer.writerow(["" if v is None else (v.date().isoformat() if hasattr(v, "date") and v.time().hour == 0 else v) for v in row])
    from_xlsx = staged_rows(extract_table(grid, "x", "d", header_rows=[1], data_rows=(2, 41)))
    from_csv = staged_rows(extract_table(read_csv(path)[0], "x", "d", header_rows=[1], data_rows=(2, 41)))
    def value(row: dict) -> str:
        if row["text"] is not None:
            return row["text"]
        return str(int(row["num"])) if float(row["num"]).is_integer() else repr(row["num"])

    key = lambda rows: sorted((r["row"], r["column"], value(r)) for r in rows)
    assert key(from_csv) == key(from_xlsx)


def test_unknown_workbook_is_profiled_generically(tmp_path: Path) -> None:
    path = tmp_path / "Seller Production.csv"
    path.write_text("API No.,Prod Month,Oil (bbl)\n42-901-14411-0000,2026-06-01,1200\n42-901-76401-0000,2026-06-01,950\n")
    tables = extract_workbook(read_csv(path), path.name, "seller-production", None)
    assert tables[0].context["family"] == "generic"
    assert [tables[0].header(c) for c in tables[0].columns] == ["API No.", "Prod Month", "Oil (bbl)"]
