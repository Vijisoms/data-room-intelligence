import json
from pathlib import Path

from data_room_intelligence.analytics import standard_answers
from data_room_intelligence.models import CanonicalModel
from data_room_intelligence.parsers import parse_unit_details
from data_room_intelligence.reporting import write_outputs

ROOT = Path(__file__).parents[1]


def test_unit_details_reconciles_asset_snapshot() -> None:
    units, metrics = parse_unit_details(
        ROOT / "Lone Star Basin Unit Details_vF_2026.08.06.xlsx"
    )
    values = {item.name: item.value for item in metrics if not item.dimensions}
    assert len(units) == 90
    assert values["unit_count"] == 90
    assert values["gross_acres"] == 70440.39
    wca = next(item for item in metrics if item.name == "net_acres" and item.dimensions == {"zone": "WCA"})
    assert round(float(wca.value), 2) == 38663.82


def test_generated_model_answers_worked_question() -> None:
    path = ROOT / "output" / "canonical-model.json"
    if not path.exists():
        return
    model = CanonicalModel.model_validate_json(path.read_text(encoding="utf-8"))
    answers = standard_answers(model)
    assert answers["worked_example_wca"]["net_acres"] > 0
    pv10 = answers["worked_example_wca"]["undeveloped_pv10_musd"]
    assert 100 < pv10 < 1000
    assert answers["worked_example_wca"]["citations"]["undeveloped_pv10_musd"]
    assert answers["value_and_economics"]["latest_net_loe_usd_boe"] > 0
    assert answers["production_and_reserves"]["historical_decline_2024_to_2025"] < 0


def test_write_outputs_creates_units_without_metrics(tmp_path: Path) -> None:
    path = ROOT / "output" / "canonical-model.json"
    if not path.exists():
        return
    model = CanonicalModel.model_validate_json(path.read_text(encoding="utf-8"))

    write_outputs(model, tmp_path, [])

    units_output = json.loads((tmp_path / "units.json").read_text(encoding="utf-8"))
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
