from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceRef(BaseModel):
    path: str
    locator: str | None = None
    as_of: str | None = None


class Metric(BaseModel):
    name: str
    value: float | int | str
    unit: str
    dimensions: dict[str, str] = Field(default_factory=dict)
    sources: list[SourceRef] = Field(default_factory=list)
    method: str | None = None


class QAFinding(BaseModel):
    severity: Literal["info", "warning", "error"]
    code: str
    message: str
    sources: list[SourceRef] = Field(default_factory=list)


class FileRecord(BaseModel):
    path: str
    kind: str
    size_bytes: int
    modified_at: datetime
    as_of: str | None = None


class UnitRecord(BaseModel):
    unit_key: str
    unit_name: str
    county: str
    development_area: str
    gross_acres: float
    lateral_length_ft: float
    zone_net_acres: dict[str, float]
    zone_wi: dict[str, float]
    zone_nri: dict[str, float]
    zone_gross_locations: dict[str, float]
    source: SourceRef


class WellRecord(BaseModel):
    well_key: str
    chosen_id: str | None = None
    well_key_source: Literal["api_14", "chosen_id", "well_name"] | None = None
    api_10: str | None = None
    api_14: str | None = None
    well_name: str
    unit_key: str | None = None
    spatial_unit_key: str | None = None
    operator: str | None = None
    operator_alias: str | None = None
    status: str
    landing_zone: str | None = None
    county: str | None = None
    wi: float | None = None
    nri: float | None = None
    net_boe_mboe: float | None = None
    pv10_musd: float | None = None
    pv10_alt_musd: float | None = None
    irr: float | None = Field(default=None, description="Fraction; source IRR (%) / 100")
    source: SourceRef


class MonthlyProduction(BaseModel):
    asset_segment: str
    month: str
    oil_bbl: float
    gas_mcf: float
    ngl_bbl: float
    boe: float
    revenue_usd: float | None = None
    loe_usd: float | None = None
    operating_income_usd: float | None = None
    source: SourceRef


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    asset_name: str
    generated_at: datetime
    data_room: str
    files: list[FileRecord]
    units: list[UnitRecord]
    wells: list[WellRecord]
    production: list[MonthlyProduction]
    metrics: list[Metric]
    findings: list[QAFinding]
    pdf_facts: dict[str, Any] = Field(default_factory=dict)
    pricing: list[dict[str, Any]] = Field(default_factory=list)
    cash_flow: list[dict[str, Any]] = Field(default_factory=list)

    def metric(self, name: str, **dimensions: str) -> Metric | None:
        for metric in self.metrics:
            if metric.name == name and all(
                metric.dimensions.get(key) == value for key, value in dimensions.items()
            ):
                return metric
        return None


class PipelineRequest(BaseModel):
    data_room: str
    output_dir: str
    asset_name: str = "Lone Star Basin"


class PipelineResult(BaseModel):
    model_path: str
    report_path: str
    fimu_path: str
    qa_path: str
    output_dir: str

    def assert_persistent(self) -> None:
        for value in (self.model_path, self.report_path, self.fimu_path, self.qa_path):
            if not Path(value).is_file():
                raise FileNotFoundError(value)
