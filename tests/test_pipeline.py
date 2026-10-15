from pathlib import Path

from data_room_intelligence.analytics import standard_answers
from data_room_intelligence.models import CanonicalModel
from data_room_intelligence.parsers import parse_unit_details

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
