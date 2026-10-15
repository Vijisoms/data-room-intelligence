from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .models import CanonicalModel, Metric


def calculate_metrics(model: CanonicalModel) -> None:
    wca = [well for well in model.wells if well.landing_zone == "WOLFCAMP A"]
    wca_undeveloped = [well for well in wca if well.status != "PRODUCING"]
    model.metrics.extend(
        [
            Metric(
                name="location_count",
                value=len(wca_undeveloped),
                unit="gross wells",
                dimensions={"zone": "WCA", "development_status": "undeveloped"},
                sources=[well.source for well in wca_undeveloped[:5]],
                method="count of non-producing WOLFCAMP A ComboCurve records",
            ),
            Metric(
                name="combocurve_net_locations",
                value=sum(well.wi or 0 for well in wca_undeveloped),
                unit="net wells",
                dimensions={"zone": "WCA", "development_status": "undeveloped"},
                sources=[well.source for well in wca_undeveloped[:5]],
                method="sum of WI across undeveloped WOLFCAMP A locations",
            ),
            Metric(
                name="pv10",
                value=sum(well.pv10_musd or 0 for well in wca_undeveloped),
                unit="MUSD",
                dimensions={"zone": "WCA", "development_status": "undeveloped"},
                sources=[well.source for well in wca_undeveloped[:5]],
                method=(
                    "sum of location-level 10% discounted cash flow; source M$ "
                    "(thousand dollars) converted to USD millions"
                ),
            ),
        ]
    )
    if model.production:
        latest_month = max(item.month for item in model.production)
        latest = [
            item
            for item in model.production
            if item.month == latest_month and item.asset_segment.endswith("NET")
        ]
        model.metrics.append(
            Metric(
                name="latest_net_production",
                value=sum(item.boe for item in latest),
                unit="BOE/month",
                dimensions={"month": latest_month},
                sources=[item.source for item in latest],
                method="sum of latest net LOS segments",
            )
        )


def standard_answers(model: CanonicalModel) -> dict[str, Any]:
    status = Counter(well.status for well in model.wells)
    zones = Counter(well.landing_zone for well in model.wells if well.landing_zone)
    wca_acres = model.metric("net_acres", zone="WCA")
    wca_unit_net_locations = model.metric("net_locations", zone="WCA")
    wca_combo_net_locations = model.metric(
        "combocurve_net_locations", zone="WCA", development_status="undeveloped"
    )
    wca_pv10 = model.metric("pv10", zone="WCA", development_status="undeveloped")
    net_segments = [item for item in model.production if item.asset_segment.endswith("NET")]
    annual_boe: dict[str, float] = defaultdict(float)
    for item in net_segments:
        annual_boe[item.month[:4]] += item.boe
    full_years = {year: value for year, value in annual_boe.items() if year in {"2024", "2025"}}
    latest_month = max((item.month for item in net_segments), default=None)
    latest_production = [item for item in net_segments if item.month == latest_month]
    latest_boe = sum(item.boe for item in latest_production)
    latest_loe = sum(item.loe_usd or 0 for item in latest_production)
    latest_pricing = model.pricing[-1] if model.pricing else {}
    undeveloped = [well for well in model.wells if well.status != "PRODUCING"]
    ranked = sorted(undeveloped, key=lambda well: well.pv10_musd or 0, reverse=True)[:10]
    metric_citations = {
        "gross_acres": _sources(model.metric("gross_acres")),
        "economic_locations": _sources(model.metric("economic_location_count")),
        "producing_wells": _sources(model.metric("producing_well_count")),
        "average_wi": _sources(model.metric("average_wi")),
        "average_nri": _sources(model.metric("average_nri")),
        "wca_net_acres": _sources(wca_acres),
        "wca_unit_net_locations": _sources(wca_unit_net_locations),
        "wca_combo_net_locations": _sources(wca_combo_net_locations),
        "wca_pv10": _sources(wca_pv10),
    }
    return {
        "asset_snapshot": {
            "units": _value(model, "unit_count"),
            "gross_acres": _value(model, "gross_acres"),
            "economic_locations": _value(model, "economic_location_count"),
            "producing_wells": _value(model, "producing_well_count"),
            "average_wi": _value(model, "average_wi"),
            "average_nri": _value(model, "average_nri"),
            "operated_fraction": _value(model, "operated_location_fraction"),
        },
        "well_status": dict(status),
        "landing_zone_counts": dict(zones),
        "ownership_and_land": {
            "counties": sorted({unit.county for unit in model.units}),
            "development_areas": sorted({unit.development_area for unit in model.units}),
            "zone_net_acres": {
                zone: model.metric("net_acres", zone=zone).value
                for zone in {item for unit in model.units for item in unit.zone_net_acres}
            },
            "zone_net_locations": {
                zone: model.metric("net_locations", zone=zone).value
                for zone in {item for unit in model.units for item in unit.zone_gross_locations}
            },
        },
        "production_and_reserves": {
            "historical_net_boe": dict(sorted(full_years.items())),
            "historical_decline_2024_to_2025": (
                full_years["2025"] / full_years["2024"] - 1
                if full_years.get("2024")
                else None
            ),
            "latest_month": latest_month,
            "latest_net_boe": latest_boe,
            "portfolio_net_boe_mboe": sum(well.net_boe_mboe or 0 for well in model.wells),
            "source": [
                item.source.model_dump(mode="json") for item in latest_production
            ],
        },
        "value_and_economics": {
            "portfolio_pv10_musd": sum(well.pv10_musd or 0 for well in model.wells),
            "latest_net_loe_usd": latest_loe,
            "latest_net_loe_usd_boe": latest_loe / latest_boe if latest_boe else None,
            "latest_basis_period": latest_pricing.get("period"),
            "latest_net_oil_usd_bbl": latest_pricing.get("net_oil_usd_bbl"),
            "latest_net_gas_usd_mcf": latest_pricing.get("net_gas_usd_mcf"),
            "latest_ngl_usd_gal": latest_pricing.get("ngl_usd_gal"),
            "pricing_source": latest_pricing.get("source"),
        },
        "portfolio_and_risk": {
            "top_undeveloped_locations": [
                {
                    "well_key": well.well_key,
                    "well_name": well.well_name,
                    "unit_key": well.unit_key,
                    "zone": well.landing_zone,
                    "pv10_musd": well.pv10_musd,
                    "irr": well.irr,
                    "source": well.source.model_dump(mode="json"),
                }
                for well in ranked
            ],
            "operator_concentration": dict(Counter(well.operator for well in model.wells)),
            "county_concentration": dict(Counter(well.county for well in model.wells)),
            "zone_concentration": dict(zones),
            "qa_finding_count": len(model.findings),
        },
        "worked_example_wca": {
            "net_acres": wca_acres.value if wca_acres else None,
            "unit_schedule_net_locations": (
                wca_unit_net_locations.value if wca_unit_net_locations else None
            ),
            "undeveloped_combocurve_net_locations": (
                wca_combo_net_locations.value if wca_combo_net_locations else None
            ),
            "undeveloped_pv10_musd": wca_pv10.value if wca_pv10 else None,
            "note": (
                "Unit schedule and ComboCurve location counts use different populations and "
                "are reported separately rather than silently forced to agree."
            ),
            "citations": {
                "net_acres": metric_citations["wca_net_acres"],
                "unit_schedule_net_locations": metric_citations["wca_unit_net_locations"],
                "undeveloped_combocurve_net_locations": metric_citations[
                    "wca_combo_net_locations"
                ],
                "undeveloped_pv10_musd": metric_citations["wca_pv10"],
            },
        },
        "citations": metric_citations,
    }


def _value(model: CanonicalModel, name: str) -> Any:
    metric = model.metric(name)
    return metric.value if metric else None


def _sources(metric: Metric | None) -> list[dict[str, Any]]:
    if metric is None:
        return []
    return [item.model_dump(mode="json") for item in metric.sources]
