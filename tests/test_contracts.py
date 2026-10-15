import pytest
from pydantic import ValidationError

from data_room_intelligence.contracts import (
    Catalog,
    DatasetSchema,
    EntityType,
    FieldMapping,
    FieldSchema,
    Manifest,
    ManifestEntry,
    RelationshipType,
    SourceLocation,
    StagedValue,
)

DATASET = "unit-details/Unit Details/C8:EG97"


def _wca_wi_field() -> FieldSchema:
    # The descriptor from ONTOLOGY_DATA_MODEL_PROPOSAL.md section 4.2.
    return FieldSchema(
        field_id="unit-details/Unit Details/CR",
        dataset_id=DATASET,
        column_ref="CR",
        header_path=["OPERATIONAL PRO FORMA WORKING INTEREST BY ZONE", "WCA"],
        inferred_type="number",
        scale="fraction (0-1)",
        rows=90,
        null_rate=0.0,
    )


def test_schema_descriptor_round_trips() -> None:
    dataset = DatasetSchema(
        dataset_id=DATASET,
        file="Lone Star Basin Unit Details_vF_2026.08.06.xlsx",
        kind="table",
        locator="Unit Details!C8:EG97",
        header_rows=[5, 6, 7],
        record_count=90,
        fields=[_wca_wi_field()],
    )
    assert DatasetSchema.model_validate_json(dataset.model_dump_json()) == dataset


def test_dataset_rejects_fields_from_another_dataset() -> None:
    stray = _wca_wi_field().model_copy(update={"dataset_id": "other"})
    with pytest.raises(ValidationError, match="fields from another dataset"):
        DatasetSchema(
            dataset_id=DATASET, file="f.xlsx", kind="table", locator="A1", record_count=0, fields=[stray]
        )


def test_staged_value_keeps_cell_location() -> None:
    value = StagedValue(
        dataset_id="combocurve/ONELINE",
        record_key="2",
        field_id="combocurve/ONELINE/LR",
        value=44.17,
        unit="percent points",
        source=SourceLocation(
            file="Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx",
            sheet="ONELINE",
            cell="LR2",
        ),
    )
    assert value.source.cell == "LR2"
    with pytest.raises(ValidationError):
        StagedValue.model_validate({**value.model_dump(), "unexpected": 1})


def test_mapping_decisions_must_be_attributed() -> None:
    proposed = FieldMapping(
        field_id="unit-details/Unit Details/CR",
        property="UnitZoneInterest.operational_wi",
        dimensions={"zone": "WCA"},
        method="rule",
    )
    assert proposed.status == "proposed"
    with pytest.raises(ValidationError, match="decided_by"):
        proposed.model_validate({**proposed.model_dump(), "status": "approved"})
    with pytest.raises(ValidationError):
        FieldMapping(field_id="x", property="not a property", method="rule")


def test_manifest_requires_sha256() -> None:
    entry = ManifestEntry(path="a.pdf", sha256="0" * 64, size_bytes=1, kind="pdf")
    Manifest(room_id="sample", snapshot_id="s1", created_at="2026-10-15T00:00:00Z", files=[entry])
    with pytest.raises(ValidationError):
        ManifestEntry(path="a.pdf", sha256="not-a-hash", size_bytes=1, kind="pdf")


def test_catalog_references_must_resolve() -> None:
    well = EntityType(name="Well", id_prefix="well", key="api_14", description="Wellbore")
    unit = EntityType(name="Unit", id_prefix="unit", key="unit_key", description="Drilling unit")
    lateral = RelationshipType(
        name="LATERAL_IN_UNIT",
        source="Well",
        target="Unit",
        method="spatial",
        build_rule="lateral within unit polygon",
    )
    catalog = Catalog(catalog_version="0.1", entity_types=[well, unit], relationship_types=[lateral])
    assert Catalog.model_validate_json(catalog.model_dump_json()) == catalog
    with pytest.raises(ValidationError, match="unknown entity types"):
        Catalog(catalog_version="0.1", entity_types=[well], relationship_types=[lateral])


@pytest.mark.parametrize(
    "contract", [Manifest, DatasetSchema, StagedValue, FieldMapping, Catalog]
)
def test_contracts_export_json_schema(contract) -> None:
    assert contract.model_json_schema()["type"] == "object"
