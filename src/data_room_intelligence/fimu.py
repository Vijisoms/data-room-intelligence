from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .models import CanonicalModel, SourceRef


class FimuLocation(BaseModel):
    location_id: str
    unit_id: str | None
    zone: str | None
    status: str
    working_interest: float | None = Field(ge=0, le=1)
    net_revenue_interest: float | None = Field(ge=0, le=1)
    net_boe_mboe: float | None
    pv10_musd: float | None
    irr_fraction: float | None
    provenance: list[SourceRef]


class FimuCase(BaseModel):
    contract: str = "draft-fimu-adapter-v0.1"
    asset_name: str
    as_of: str
    unit_system: str = "field"
    locations: list[FimuLocation]
    validation_warnings: list[str]


def build_fimu_case(model: CanonicalModel) -> FimuCase:
    locations = [
        FimuLocation(
            location_id=well.well_key,
            unit_id=well.unit_key,
            zone=well.landing_zone,
            status=well.status,
            working_interest=well.wi,
            net_revenue_interest=well.nri,
            net_boe_mboe=well.net_boe_mboe,
            pv10_musd=well.pv10_musd,
            irr_fraction=well.irr,
            provenance=[well.source],
        )
        for well in model.wells
    ]
    warnings: list[str] = []
    if any(item.unit_id is None for item in locations):
        warnings.append("Some locations do not have a reconciled unit key.")
    warnings.append("Replace the draft adapter contract after the authoritative FIMU schema is supplied.")
    return FimuCase(
        asset_name=model.asset_name,
        as_of="2026-10-01",
        locations=locations,
        validation_warnings=warnings,
    )

