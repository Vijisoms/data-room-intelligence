import json
from pathlib import Path

import pytest

from data_room_intelligence.analytics import standard_answers
from data_room_intelligence.discovery import discover
from data_room_intelligence.models import CanonicalModel, PipelineRequest, WellRecord
from data_room_intelligence.parsers import parse_unit_details
from data_room_intelligence.pipeline import run_pipeline
from data_room_intelligence.reporting import write_outputs

ROOT = Path(__file__).parents[1]
ROOM = ROOT / "data" / "sample-room"
JARDINE_API_14 = "42901144110000"


@pytest.fixture(scope="session")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[CanonicalModel, Path]:
    output = tmp_path_factory.mktemp("output")
    result = run_pipeline(PipelineRequest(data_room=str(ROOM), output_dir=str(output)))
    model = CanonicalModel.model_validate_json(Path(result.model_path).read_text("utf-8"))
    return model, output


def test_unit_details_reconciles_asset_snapshot() -> None:
    units, metrics = parse_unit_details(ROOM / "Lone Star Basin Unit Details_vF_2026.08.06.xlsx")
    values = {item.name: item.value for item in metrics if not item.dimensions}
    assert len(units) == 90
    assert values["unit_count"] == 90
    assert values["gross_acres"] == 70440.39
    wca = next(item for item in metrics if item.name == "net_acres" and item.dimensions == {"zone": "WCA"})
    assert round(float(wca.value), 2) == 38663.82


def test_discovery_is_scoped_to_the_room() -> None:
    files = discover(ROOM)
    assert len(files) == 26
    assert all(not Path(item.path).is_absolute() for item in files)
    assert not any(part.startswith((".", "~$")) for item in files for part in Path(item.path).parts)
    assert sum(item.kind == "gis_units" for item in files) == 2


def test_combocurve_is_read_natively_with_identifiers_intact(built) -> None:
    model, _ = built
    wells = model.wells
    assert len(wells) == 640
    assert len({well.api_14 for well in wells if well.api_14}) == 320
    assert all(len(well.api_14) == 14 for well in wells if well.api_14)
    assert sum(well.irr is not None for well in wells) == 640
    assert all(0.15 <= well.irr <= 1.2 for well in wells)
    assert sum(well.pv10_musd is not None and well.pv10_alt_musd is not None for well in wells) == 640
    jardine = next(well for well in wells if well.api_14 == JARDINE_API_14)
    assert jardine.api_10 == "4290114411"
    assert jardine.operator_alias == "NON-OP"
    assert round(jardine.pv10_musd, 3) == 6.817
    assert round(jardine.pv10_alt_musd, 3) == 5.936
    assert round(jardine.irr, 4) == 0.4417


def test_reconciliation_keeps_both_unit_assignments(built) -> None:
    model, _ = built
    jardine = next(well for well in model.wells if well.api_14 == JARDINE_API_14)
    assert jardine.unit_key == "BADGER_DRAW"
    assert jardine.spatial_unit_key == "GOLDEN_CROSSING_WEST"
    assert sum(bool(well.spatial_unit_key) for well in model.wells) == 320
    assert len({well.unit_key for well in model.wells}) == 90
    findings = {item.code: item.message for item in model.findings}
    assert findings["UNIT_ASSIGNMENT_CONFLICT"].startswith("317 of 320")
    assert "for 640 of 640" in findings["VALUE_FIELD_CONFLICT"]
    assert "483 of them" in findings["OPERATOR_ALIAS_CONFLICT"]
    assert "PDP_COUNT_RECONCILED" in findings


def test_outputs_have_no_machine_specific_paths(built) -> None:
    model, output = built
    assert model.data_room == "data/sample-room"
    for path in output.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert str(ROOT) not in text, path.name
            assert "C:\\" not in text and "/Users/" not in text, path.name


def test_generated_model_answers_worked_question(built) -> None:
    model, _ = built
    answers = standard_answers(model)
    wca = answers["worked_example_wca"]
    assert round(wca["net_acres"], 2) == 38663.82
    assert round(wca["unit_schedule_net_locations"], 2) == 96.98
    assert round(wca["undeveloped_pv10_musd"], 1) == 356.1
    assert wca["citations"]["undeveloped_pv10_musd"]
    assert answers["value_and_economics"]["latest_net_loe_usd_boe"] > 0
    assert answers["production_and_reserves"]["historical_decline_2024_to_2025"] < 0


def test_write_outputs_creates_units_without_metrics(built, tmp_path: Path) -> None:
    model, _ = built

    write_outputs(model, tmp_path, [])

    parsed_dir = tmp_path / "parsed_json"
    units_output = json.loads((parsed_dir / "units.json").read_text(encoding="utf-8"))
    assert units_output["schema_version"] == model.schema_version
    assert units_output["asset_name"] == model.asset_name
    assert len(units_output["units"]) == 90
    assert "metrics" not in units_output
    assert set(units_output["units"][0]) == {
        "unit_key",
        "unit_name",
        "county",
        "development_area",
        "gross_acres",
        "lateral_length_ft",
        "zone_net_acres",
        "zone_wi",
        "zone_nri",
        "zone_gross_locations",
        "source",
    }
    wells_output = json.loads((parsed_dir / "wells.json").read_text(encoding="utf-8"))
    assert wells_output["schema_version"] == model.schema_version
    assert wells_output["asset_name"] == model.asset_name
    assert len(wells_output["wells"]) == 640
    assert "metrics" not in wells_output
    assert {"well_key", "chosen_id", "well_key_source"} <= set(
        wells_output["wells"][0]
    )
    expected_collections = {
        "cash_flow.json": "cash_flow",
        "combo_metrics.json": "metrics",
        "spatial_links.json": "spatial_links",
        "gis_metrics.json": "metrics",
        "production.json": "production",
        "pdf_facts.json": "pdf_facts",
        "pricing.json": "pricing",
    }
    for filename, collection in expected_collections.items():
        payload = json.loads((parsed_dir / filename).read_text(encoding="utf-8"))
        assert collection in payload
        assert "metrics" not in payload or collection == "metrics"

    for filename in {
        "unit-details-parsing.md",
        "well-parsing.md",
        "cash-flow-parsing.md",
        "combo-metrics-parsing.md",
        "spatial-links-parsing.md",
        "gis-metrics-parsing.md",
        "production-parsing.md",
        "pdf-facts-parsing.md",
        "pricing-parsing.md",
        "metrics-parsing.md",
        "pipeline-finalization.md",
    }:
        assert (parsed_dir / filename).read_text(encoding="utf-8").startswith("# ")


def test_well_record_preserves_identifier_provenance() -> None:
    well = WellRecord(
        well_key="LSB-WCA-001",
        chosen_id="LSB-WCA-001",
        well_key_source="chosen_id",
        well_name="DESERT BASIN WCA 1H",
        status="UNDEVELOPED",
        source={
            "path": "combocurve.xlsx",
            "locator": "ONELINE!row 2",
        },
    )

    payload = well.model_dump(mode="json")
    assert payload["well_key"] == "LSB-WCA-001"
    assert payload["chosen_id"] == "LSB-WCA-001"
    assert payload["well_key_source"] == "chosen_id"
