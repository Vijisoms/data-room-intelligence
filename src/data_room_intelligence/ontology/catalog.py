from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

import yaml

from ..contracts import AliasTable, Catalog, RuleSet

REPO_ROOT = Path(__file__).resolve().parents[3]
TURTLE_NAMESPACE = "https://example.org/data-room-intelligence/ontology#"
JSON_TYPES = {
    "string": {"type": "string"},
    "number": {"type": "number"},
    "integer": {"type": "integer"},
    "boolean": {"type": "boolean"},
    "date": {"type": "string", "format": "date"},
    "datetime": {"type": "string", "format": "date-time"},
    "geometry": {"type": "object", "description": "GeoJSON geometry, EPSG:4326"},
    "empty": {"type": "null"},
}
XSD_TYPES = {
    "string": "xsd:string",
    "number": "xsd:decimal",
    "integer": "xsd:integer",
    "boolean": "xsd:boolean",
    "date": "xsd:date",
    "datetime": "xsd:dateTime",
    "geometry": "geo:wktLiteral",
    "empty": "xsd:string",
}


def catalog_dir() -> Path:
    return Path(os.environ.get("DRI_CATALOG_DIR", REPO_ROOT / "ontology"))


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def load_catalog(directory: Path | None = None) -> Catalog:
    return Catalog.model_validate(_read((directory or catalog_dir()) / "catalog.yaml"))


@lru_cache(maxsize=4)
def load_rules(directory: Path | None = None) -> RuleSet:
    rules = RuleSet.model_validate(_read((directory or catalog_dir()) / "rules.yaml"))
    names = {item.name for item in load_catalog(directory).entity_types}
    unknown = sorted({rule.subject for rule in rules.rules} - names)
    if unknown:
        raise ValueError(f"rules reference unknown entity types: {unknown}")
    return rules


@lru_cache(maxsize=4)
def load_aliases(directory: Path | None = None) -> dict[str, AliasTable]:
    folder = (directory or catalog_dir()) / "aliases"
    tables = [AliasTable.model_validate(_read(path)) for path in sorted(folder.glob("*.yaml"))]
    return {table.name: table for table in tables}


def catalog_fingerprint(directory: Path | None = None) -> str:
    folder = directory or catalog_dir()
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*.yaml")):
        digest.update(path.relative_to(folder).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def export_catalog(out_dir: Path, directory: Path | None = None) -> list[Path]:
    """Write the reviewable artifacts generated from the catalog."""
    catalog = load_catalog(directory)
    rules = load_rules(directory)
    aliases = load_aliases(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "catalog.md": render_dictionary(catalog, rules, aliases),
        "catalog.mmd": render_mermaid(catalog),
        "catalog.schema.json": json.dumps(render_json_schema(catalog), indent=2) + "\n",
        "catalog.ttl": render_turtle(catalog),
    }
    paths = []
    for name, content in outputs.items():
        path = out_dir / name
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return paths


def render_dictionary(catalog: Catalog, rules: RuleSet, aliases: dict[str, AliasTable]) -> str:
    lines = [
        "# Ontology Catalog: Data Dictionary",
        "",
        f"Catalog version **{catalog.catalog_version}**, status: **{catalog.status}**. "
        "Generated from `ontology/` by `data-room-intel catalog export`; do not edit by hand.",
        "",
        catalog.description or "",
        "",
        "```mermaid",
        render_mermaid(catalog).rstrip(),
        "```",
        "",
        "## Entity Types",
        "",
        "| Entity type | ID pattern | Key | Standard | Description |",
        "|---|---|---|---|---|",
    ]
    for entity in catalog.entity_types:
        lines.append(
            f"| {entity.name} | `{entity.id_prefix}:<{entity.key}>` | `{entity.key}` | "
            f"{entity.standard or 'Custom'} | {entity.description} |"
        )
    for entity in catalog.entity_types:
        lines += ["", f"### {entity.name}", "", "| Property | Type | Unit | Required | Source and meaning |", "|---|---|---|---|---|"]
        for prop in entity.properties:
            lines.append(
                f"| `{prop.name}` | {prop.type} | {prop.unit or ''} | {'yes' if prop.required else ''} | {prop.description or ''} |"
            )
    lines += ["", "## Relationship Types", "", "| Relationship | From | To | Method | Build rule |", "|---|---|---|---|---|"]
    for rel in catalog.relationship_types:
        lines.append(f"| `{rel.name}` | {rel.source} | {rel.target} | {rel.method} | {rel.build_rule} |")
    lines += ["", "## Measures (Facts)", "", "| Measure | Subject | Unit | Dimensions | Sources | Description |", "|---|---|---|---|---|---|"]
    for measure in catalog.measures:
        lines.append(
            f"| `{measure.name}` | {measure.subject} | {measure.unit} | {', '.join(measure.dimensions)} | "
            f"{'; '.join(measure.sources) or 'none in sample room'} | {measure.description} |"
        )
    lines += ["", f"## Reconciliation Rules (version {rules.rules_version})", "", "| Rule | Subject | Check | Severity | Blocks |", "|---|---|---|---|---|"]
    for rule in rules.rules:
        lines.append(f"| `{rule.code}` | {rule.subject} | {rule.check} | {rule.severity} | {rule.blocks} |")
    lines += ["", "## Alias Tables"]
    for table in aliases.values():
        lines += ["", f"### {table.name} ({table.status})", "", table.description, "", f"Applies to: {table.applies_to}", "", "| Source value | Maps to |", "|---|---|"]
        for source, target in table.entries.items():
            lines.append(f"| {source} | {target if target is not None else '**unmapped, decision needed**'} |")
    return "\n".join(lines) + "\n"


def render_mermaid(catalog: Catalog) -> str:
    lines = ["classDiagram", "  direction LR"]
    for entity in catalog.entity_types:
        lines.append(f"  class {entity.name} {{")
        for prop in entity.properties:
            lines.append(f"    +{prop.type} {prop.name}")
        lines.append("  }")
    for rel in catalog.relationship_types:
        lines.append(f"  {rel.source} --> {rel.target} : {rel.name}")
    return "\n".join(lines) + "\n"


def render_json_schema(catalog: Catalog) -> dict:
    definitions = {}
    for entity in catalog.entity_types:
        properties = {"id": {"type": "string", "pattern": f"^{entity.id_prefix}:"}}
        for prop in entity.properties:
            schema = dict(JSON_TYPES[prop.type])
            description = " ".join(part for part in (prop.description, f"Unit: {prop.unit}." if prop.unit else None) if part)
            if description:
                schema["description"] = description
            properties[prop.name] = schema
        definitions[entity.name] = {
            "type": "object",
            "description": entity.description,
            "properties": properties,
            "required": ["id", *[prop.name for prop in entity.properties if prop.required]],
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"Data Room Intelligence catalog {catalog.catalog_version}",
        "$defs": definitions,
        "oneOf": [{"$ref": f"#/$defs/{name}"} for name in definitions],
    }


def render_turtle(catalog: Catalog) -> str:
    def literal(text: str) -> str:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines = [
        "# Generated from ontology/catalog.yaml. Replace the namespace when XOM assigns one.",
        "# Measures are dimensional facts and are documented in catalog.md, not modeled as OWL properties.",
        f"@prefix dri: <{TURTLE_NAMESPACE}> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix geo: <http://www.opengis.net/ont/geosparql#> .",
        "",
        f"<{TURTLE_NAMESPACE.rstrip('#')}> a owl:Ontology ;",
        f"  owl:versionInfo {literal(catalog.catalog_version)} ;",
        f"  rdfs:comment {literal(catalog.description or '')} .",
    ]
    for entity in catalog.entity_types:
        lines += ["", f"dri:{entity.name} a owl:Class ;", f"  rdfs:label {literal(entity.name)} ;", f"  rdfs:comment {literal(entity.description)} ."]
        for prop in entity.properties:
            lines += [
                f"dri:{entity.id_prefix}_{prop.name} a owl:DatatypeProperty ;",
                f"  rdfs:label {literal(f'{entity.name}.{prop.name}')} ;",
                f"  rdfs:domain dri:{entity.name} ;",
                f"  rdfs:range {XSD_TYPES[prop.type]} ;",
                f"  rdfs:comment {literal(prop.description or '')} .",
            ]
    for rel in catalog.relationship_types:
        lines += [
            "",
            f"dri:{rel.name} a owl:ObjectProperty ;",
            f"  rdfs:label {literal(rel.name)} ;",
            f"  rdfs:domain dri:{rel.source} ;",
            f"  rdfs:range dri:{rel.target} ;",
            f"  rdfs:comment {literal(f'{rel.method}: {rel.build_rule}')} .",
        ]
    return "\n".join(lines) + "\n"
