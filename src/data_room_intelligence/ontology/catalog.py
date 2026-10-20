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


def catalog_fingerprint(directory: Path | None = None, room_id: str | None = None) -> str:
    """Hash of the governed base files plus, for a project, its model extension."""
    folder = directory or catalog_dir()
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*.yaml")):
        digest.update(path.relative_to(folder).as_posix().encode())
        digest.update(path.read_bytes())
    if room_id:
        extension = extension_path(room_id)
        if extension.exists():
            digest.update(b"extension")
            digest.update(extension.read_bytes())
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Project model extensions: the governed base catalog plus per-project additions.
# ---------------------------------------------------------------------------

EMPTY_EXTENSION: dict[str, list] = {"entity_types": [], "properties": [], "measures": [], "relationship_types": [], "header_rules": []}
CHANGE_OPS = {"add_entity_type", "add_property", "add_measure", "add_relationship", "add_header_rule"}


def extension_path(room_id: str) -> Path:
    from ..config import RoomPaths

    return RoomPaths(room_id).catalog / "extension.yaml"


def load_extension(room_id: str | None) -> dict[str, list]:
    path = extension_path(room_id) if room_id else None
    if not path or not path.exists():
        return {key: [] for key in EMPTY_EXTENSION}
    data = yaml.safe_load(path.read_text("utf-8")) or {}
    return {key: list(data.get(key) or []) for key in EMPTY_EXTENSION}


def catalog_changes(room_id: str) -> list[dict]:
    from ..config import RoomPaths

    path = RoomPaths(room_id).catalog / "changes.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def merge_catalog(base: Catalog, extension: dict[str, list], version: str, status: str | None = None) -> Catalog:
    data = base.model_dump(mode="json")
    data["catalog_version"] = version
    if status:
        data["status"] = status
    data["entity_types"] = [*data["entity_types"], *extension["entity_types"]]
    for addition in extension["properties"]:
        entity = next((e for e in data["entity_types"] if e["name"] == addition["entity_type"]), None)
        if entity is None:
            raise ValueError(f"property addition for unknown entity type {addition['entity_type']}")
        if all(p["name"] != addition["property"]["name"] for p in entity["properties"]):
            entity["properties"].append(addition["property"])
    data["measures"] = [*data["measures"], *extension["measures"]]
    data["relationship_types"] = [*data["relationship_types"], *extension["relationship_types"]]
    return Catalog.model_validate(data)


def room_catalog(room_id: str | None, directory: Path | None = None) -> Catalog:
    """The model a project builds with: base catalog plus its approved extension (versioned by change count)."""
    base = load_catalog(directory)
    if not room_id:
        return base
    extension = load_extension(room_id)
    changes = catalog_changes(room_id)
    if not changes and not any(extension.values()):
        return base
    version = f"{base.catalog_version}+{room_id}.{len(changes)}"
    return merge_catalog(base, extension, version, f"{base.status}; {len(changes)} project change set{'s' if len(changes) != 1 else ''}")


def room_header_rules(room_id: str | None) -> list[dict]:
    rules = yaml.safe_load((catalog_dir() / "header_rules.yaml").read_text("utf-8"))["rules"]
    return [*rules, *load_extension(room_id)["header_rules"]]


def apply_changes(room_id: str, items: list[dict], applied_by: str, reason: str, proposal_id: str | None = None) -> dict:
    """Apply an approved change set to the project extension; the merged catalog must validate or nothing is written."""
    from ..config import RoomPaths
    from datetime import datetime, timezone

    extension = load_extension(room_id)
    for item in items:
        op = item.get("op")
        if op not in CHANGE_OPS:
            raise ValueError(f"unknown change operation {op}")
        if op == "add_entity_type":
            if any(e["name"] == item["entity_type"]["name"] for e in extension["entity_types"]):
                continue
            extension["entity_types"].append(item["entity_type"])
        elif op == "add_property":
            key = (item["entity_type"], item["property"]["name"])
            if any((p["entity_type"], p["property"]["name"]) == key for p in extension["properties"]):
                continue
            extension["properties"].append({"entity_type": item["entity_type"], "property": item["property"]})
        elif op == "add_measure":
            key = (item["measure"]["subject"], item["measure"]["name"])
            if any((m["subject"], m["name"]) == key for m in extension["measures"]):
                continue
            extension["measures"].append(item["measure"])
        elif op == "add_relationship":
            if any(r["name"] == item["relationship"]["name"] for r in extension["relationship_types"]):
                continue
            extension["relationship_types"].append(item["relationship"])
        elif op == "add_header_rule":
            if any(r["pattern"] == item["rule"]["pattern"] and r["target"] == item["rule"]["target"] for r in extension["header_rules"]):
                continue
            extension["header_rules"].append(item["rule"])
    changes = catalog_changes(room_id)
    base = load_catalog()
    merged = merge_catalog(base, extension, f"{base.catalog_version}+{room_id}.{len(changes) + 1}")  # raises on dangling references
    paths = RoomPaths(room_id)
    paths.catalog.mkdir(parents=True, exist_ok=True)
    extension_path(room_id).write_text(yaml.safe_dump(extension, sort_keys=False, allow_unicode=True), encoding="utf-8")
    record = {
        "change_id": f"change:{len(changes) + 1}",
        "catalog_version": merged.catalog_version,
        "proposal_id": proposal_id,
        "items": items,
        "applied_by": applied_by,
        "reason": reason,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    with (paths.catalog / "changes.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")
    return record


def copy_extension(source_room: str, target_room: str) -> None:
    """Start a project from another project's model: the extension is copied as one change set."""
    extension = load_extension(source_room)
    items = [
        *({"op": "add_entity_type", "entity_type": e} for e in extension["entity_types"]),
        *({"op": "add_property", **p} for p in extension["properties"]),
        *({"op": "add_measure", "measure": m} for m in extension["measures"]),
        *({"op": "add_relationship", "relationship": r} for r in extension["relationship_types"]),
        *({"op": "add_header_rule", "rule": r} for r in extension["header_rules"]),
    ]
    if items:
        apply_changes(target_room, items, "system", f"copied from project {source_room}")


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
