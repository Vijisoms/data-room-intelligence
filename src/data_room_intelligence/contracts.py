"""Shared data contracts between pipeline stages (ontology proposal section 4.1).

Discovery writes a Manifest. Parsers write DatasetSchema descriptors and StagedValue
records. Mapping writes FieldMapping rows. The ontology build reads the Catalog.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = "0.1"

FileKind = Literal["excel", "csv", "gis_layer", "gis_sidecar", "pdf", "presentation", "other"]
Protection = Literal["none", "password", "rights_management", "unknown"]
ValueType = Literal["string", "number", "integer", "boolean", "date", "datetime", "geometry", "empty"]
DatasetKind = Literal["table", "feature_layer", "document_page", "document_figure"]
ValueQuality = Literal["ok", "approximate", "uncached_formula", "suspect"]
MappingMethod = Literal["rule", "alias", "model", "human"]
MappingStatus = Literal["proposed", "approved", "rejected"]
RelationshipMethod = Literal[
    "source", "key", "alias", "spatial", "crosswalk", "document", "rule", "human"
]
Scalar = str | float | int | bool | None


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceLocation(Contract):
    """Where a value came from, precise enough for the input viewer to highlight it."""

    file: str = Field(description="Room-relative POSIX path")
    sheet: str | None = None
    cell: str | None = Field(default=None, description="A1 cell or range, e.g. KY2 or C8:EG97")
    row: int | None = Field(default=None, ge=1)
    column: str | None = None
    layer: str | None = None
    feature_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = Field(
        default=None, description="x0, y0, x1, y1 in page units"
    )


class ManifestEntry(Contract):
    path: str = Field(description="Room-relative POSIX path")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    kind: FileKind
    role: str | None = Field(default=None, description="Role guess, e.g. economics_oneline")
    role_confidence: float | None = Field(default=None, ge=0, le=1)
    bundle: str | None = Field(default=None, description="Group key, e.g. a shapefile stem")
    protection: Protection = "none"
    as_of: str | None = Field(default=None, description="ISO date hint")


class Manifest(Contract):
    contract_version: str = CONTRACT_VERSION
    room_id: str
    snapshot_id: str
    created_at: datetime
    files: list[ManifestEntry]
    skipped: list[str] = Field(default_factory=list, description="e.g. Office lock files")


class FieldSchema(Contract):
    field_id: str
    dataset_id: str
    column_ref: str | None = None
    header_path: list[str]
    inferred_type: ValueType
    unit: str | None = None
    scale: str | None = Field(default=None, description="e.g. fraction (0-1), percent points")
    rows: int = Field(ge=0)
    null_rate: float = Field(ge=0, le=1)
    distinct_count: int | None = Field(default=None, ge=0)
    samples: list[Scalar] = Field(default_factory=list)
    formula_count: int = Field(default=0, ge=0)
    uncached_formula_count: int = Field(default=0, ge=0)
    candidate_key: bool = False


class DatasetSchema(Contract):
    dataset_id: str
    file: str
    kind: DatasetKind
    locator: str = Field(description="Sheet range, layer name or page")
    header_rows: list[int] = Field(default_factory=list)
    record_count: int = Field(ge=0)
    fields: list[FieldSchema]
    crs: str | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fields_belong_to_dataset(self) -> DatasetSchema:
        stray = [item.field_id for item in self.fields if item.dataset_id != self.dataset_id]
        if stray:
            raise ValueError(f"fields from another dataset: {stray}")
        return self


class StagedValue(Contract):
    dataset_id: str
    record_key: str = Field(description="Row number, feature ID or claim ID")
    field_id: str
    value: Scalar
    raw: str | None = Field(default=None, description="Stored text when it differs from value")
    unit: str | None = None
    source: SourceLocation
    quality: ValueQuality = "ok"


class FieldMapping(Contract):
    field_id: str
    property: str = Field(pattern=r"^[A-Z][A-Za-z]+\.[a-z0-9_]+$", description="Type.property")
    dimensions: dict[str, str] = Field(default_factory=dict)
    transform: str | None = Field(default=None, description="e.g. divide:100")
    method: MappingMethod
    status: MappingStatus = "proposed"
    confidence: float | None = Field(default=None, ge=0, le=1)
    rationale: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None

    @model_validator(mode="after")
    def _decisions_are_attributed(self) -> FieldMapping:
        if self.status != "proposed" and not self.decided_by:
            raise ValueError("approved or rejected mappings need decided_by")
        return self


class PropertyDef(Contract):
    name: str = Field(pattern=r"^[a-z0-9_]+$")
    type: ValueType
    unit: str | None = None
    description: str | None = None
    required: bool = False


class EntityType(Contract):
    name: str = Field(pattern=r"^[A-Z][A-Za-z]+$")
    id_prefix: str = Field(pattern=r"^[a-z][a-z_]*$", description="Prefix of type:key IDs")
    key: str = Field(description="Property that forms the deterministic ID")
    description: str
    properties: list[PropertyDef] = Field(default_factory=list)
    standard: str | None = Field(default=None, description="e.g. OSDU master-data--Well")


class RelationshipType(Contract):
    name: str = Field(pattern=r"^[A-Z][A-Z_]+$")
    source: str
    target: str
    method: RelationshipMethod
    build_rule: str
    description: str | None = None


class Catalog(Contract):
    catalog_version: str
    entity_types: list[EntityType]
    relationship_types: list[RelationshipType]

    @model_validator(mode="after")
    def _references_resolve(self) -> Catalog:
        names = [item.name for item in self.entity_types]
        if len(names) != len(set(names)):
            raise ValueError("duplicate entity type names")
        prefixes = [item.id_prefix for item in self.entity_types]
        if len(prefixes) != len(set(prefixes)):
            raise ValueError("duplicate entity ID prefixes")
        unknown = sorted(
            {
                end
                for relationship in self.relationship_types
                for end in (relationship.source, relationship.target)
                if end not in names
            }
        )
        if unknown:
            raise ValueError(f"relationships reference unknown entity types: {unknown}")
        return self
