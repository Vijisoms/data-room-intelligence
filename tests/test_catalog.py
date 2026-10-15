from pathlib import Path

import pytest
from rdflib import Graph
from rdflib.namespace import OWL, RDF

from data_room_intelligence.ontology.catalog import (
    export_catalog,
    load_aliases,
    load_catalog,
    load_rules,
)

ROOT = Path(__file__).parents[1]


def test_catalog_validates_with_expected_shape() -> None:
    catalog = load_catalog()
    assert len(catalog.entity_types) == 14
    assert len(catalog.relationship_types) == 15
    assert len(catalog.measures) == 27
    assert {rule.code for rule in load_rules().rules} >= {
        "UNIT_ASSIGNMENT_CONFLICT",
        "OWNERSHIP_VALUE_CONFLICT",
        "VALUE_FIELD_CONFLICT",
        "ZONE_ALIAS_MISSING",
    }
    landing = load_aliases()["landing_zones"]
    assert landing.status == "proposed"
    assert landing.entries["WOLFCAMP A"] == "WCA"
    assert landing.entries["LWR SPRB SAND"] is None


def test_generated_review_artifacts_are_current(tmp_path: Path) -> None:
    for path in export_catalog(tmp_path):
        committed = ROOT / "docs" / "catalog" / path.name
        assert committed.read_text("utf-8") == path.read_text("utf-8"), (
            f"{committed} is stale; run: data-room-intel catalog export"
        )


def test_turtle_export_is_valid_owl(tmp_path: Path) -> None:
    export_catalog(tmp_path)
    graph = Graph().parse(tmp_path / "catalog.ttl", format="turtle")
    assert len(set(graph.subjects(RDF.type, OWL.Class))) == 14
    assert len(set(graph.subjects(RDF.type, OWL.ObjectProperty))) == 15


def test_catalog_rejects_dangling_relationship(tmp_path: Path) -> None:
    source = (ROOT / "ontology" / "catalog.yaml").read_text("utf-8")
    (tmp_path / "catalog.yaml").write_text(
        source.replace("target: PricingFacility", "target: PricingHub"), "utf-8"
    )
    with pytest.raises(ValueError, match="PricingHub"):
        load_catalog(tmp_path)
