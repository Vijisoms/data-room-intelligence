"""Concept discovery: when a new file brings something the model does not have, propose a model change.

A proposal is a change set for the project's model extension (see catalog.py) plus the header rules that
map the file's columns to the new or extended type. Nothing is applied until the data steward approves it;
approval bumps the project's catalog version and the next rebuild creates the entities, links and facts.

Three cases, decided from the data:

- `new_entity`: no column matches an existing entity key, but one column identifies the rows. A new entity
  type is proposed, with its properties (text and date columns), measures (numeric columns) and
  relationships (columns whose values match an existing type's key, such as a Unit or County column).
- `extend_entity`: the rows describe an existing type, but some columns fit no property or measure it has.
  Those columns are proposed as additions to that type (or as a new relationship when their values match
  another type's key and the catalog declares no relationship between the two types).
- `link_table`: no identifying column, but two columns match two different existing types: the file is a
  crosswalk. A relationship is proposed (or an existing one is bound) between the two types.

Names and descriptions are drafted by the chat model when it is available, from the headers, sample values
and the catalog's naming conventions; offline, they are derived from the headers.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..config import RoomPaths, offline
from ..contracts import Catalog, EntityType, MeasureDef, PropertyDef, RelationshipType
from .build import Gold, Silver
from .mapping import _cached, _store, column_profiles, entity_keys, header_key, key_targets, overlaps

ID_WORDS = re.compile(r"(^|\s)(id|no|num|number|code|key|identifier)(\s|$)")
GEO_TARGETS = {"Unit", "County", "DevelopmentArea", "Asset", "LeaseholdTract", "Zone"}
GENERIC_SHEETS = re.compile(r"^(sheet\s*\d*|data|table\s*\d*|export|report)$", re.I)
UNIT_PATTERN = re.compile(r"\(([^()]+)\)\s*$")


def proposals_dir(room_id: str) -> Path:
    return RoomPaths(room_id).catalog / "proposals"


def list_proposals(room_id: str) -> list[dict[str, Any]]:
    folder = proposals_dir(room_id)
    items = [json.loads(p.read_text("utf-8")) for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []
    return sorted(items, key=lambda p: ({"proposed": 0, "approved": 1, "rejected": 2}.get(p["status"], 3), p.get("created_at") or ""))


def get_proposal(room_id: str, proposal_id: str) -> dict[str, Any] | None:
    path = proposals_dir(room_id) / f"{proposal_id}.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else None


def save_proposal(room_id: str, proposal: dict[str, Any]) -> dict[str, Any]:
    folder = proposals_dir(room_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{proposal['proposal_id']}.json").write_text(json.dumps(proposal, indent=1, default=str), encoding="utf-8")
    return proposal


def decide_proposal(room_id: str, proposal_id: str, status: str, reviewer: str, reason: str, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Approve (optionally with edited items) or reject a proposal. Approval applies the change set to the project model."""
    from .catalog import apply_changes

    proposal = get_proposal(room_id, proposal_id)
    if proposal is None:
        raise KeyError(proposal_id)
    if status not in {"approved", "rejected"}:
        raise ValueError("status must be approved or rejected")
    if status == "approved":
        change = apply_changes(room_id, items or proposal["items"], reviewer, reason, proposal_id)
        proposal["items"] = items or proposal["items"]
        proposal["change_id"] = change["change_id"]
        proposal["catalog_version"] = change["catalog_version"]
    proposal.update({"status": status, "decided_by": reviewer, "decided_at": datetime.now(timezone.utc).isoformat(), "reason": reason})
    return save_proposal(room_id, proposal)


# ---------------------------------------------------------------------------
# Naming helpers (offline drafts; the model refines them when available)
# ---------------------------------------------------------------------------


def snake(text: str) -> str:
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    name = "_".join(words) or "value"
    return name if re.match(r"^[a-z]", name) else f"f_{name}"


def pascal(text: str) -> str:
    words = re.sub(r"[^A-Za-z0-9]+", " ", text).split()
    return "".join(w[:1].upper() + w[1:].lower() for w in words) or "Record"


def singular(word: str) -> str:
    if word.lower().endswith("ies"):
        return word[:-3] + "y"
    if word.lower().endswith(("ses", "xes", "ches", "shes")):
        return word[:-2]
    if word.lower().endswith("s") and not word.lower().endswith("ss"):
        return word[:-1]
    return word


def draft_type_name(sheet: str, file: str, key_header: str, existing: set[str]) -> str:
    """A PascalCase singular noun from the sheet name (unless generic), else the file name, else the key header."""
    source = sheet if sheet and not GENERIC_SHEETS.match(sheet.strip()) else Path(file).stem
    source = re.sub(r"[_\-.]?\d{4}[._-]?\d{2}([._-]?\d{2})?", " ", source)  # drop dates
    source = re.sub(r"\b(schedule|register|list|export|report|detail|details|summary|data|table|master|file)\b", " ", source, flags=re.I)
    words = [w for w in re.sub(r"[^A-Za-z0-9]+", " ", source).split() if w.lower() not in {"the", "of", "and", "lone", "star", "basin", "lsb"}]
    if not words:
        words = re.sub(r"[^A-Za-z]+", " ", key_header).split()[:1] or ["Record"]
    name = pascal(" ".join(singular(w) for w in words[:2]))
    base = name
    counter = 2
    while name in existing:
        name, counter = f"{base}{counter}", counter + 1
    return name


def draft_prefix(type_name: str, existing: set[str]) -> str:
    prefix = re.sub(r"[^a-z]", "", type_name.lower()) or "entity"
    base, counter = prefix, 2
    while prefix in existing:
        prefix, counter = f"{base}{counter}", counter + 1
    return prefix


def relationship_name(subject: str, target: str, existing: set[str]) -> str:
    verb = "IN" if target in GEO_TARGETS else "FOR" if target in {"Well", "EconomicLocation"} else "TO"
    name = f"{re.sub(r'(?<!^)(?=[A-Z])', '_', subject).upper()}_{verb}_{re.sub(r'(?<!^)(?=[A-Z])', '_', target).upper()}"
    base, counter = name, 2
    while name in existing:
        name, counter = f"{base}_{counter}", counter + 1
    return name


def _unit_of(header: str) -> str:
    match = UNIT_PATTERN.search(header)
    if match:
        return match.group(1).strip()
    lowered = header.lower()
    for word, unit in (("acre", "acres"), ("royalty", "fraction"), ("interest", "fraction"), ("percent", "fraction"), ("%", "fraction"), ("bbl", "bbl"), ("mcf", "mcf"), ("ft", "ft"), ("feet", "ft"), ("depth", "ft"), ("$", "$"), ("cost", "$"), ("amount", "$")):
        if word in lowered:
            return unit
    return ""


def _value_type(values: list[Any]) -> str:
    if not values:
        return "string"
    if all(isinstance(v, bool) for v in values):
        return "boolean"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return "integer" if all(float(v).is_integer() for v in values) else "number"
    if all(isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) for v in values):
        return "date"
    return "string"


# ---------------------------------------------------------------------------
# Model drafting (names, descriptions, standards)
# ---------------------------------------------------------------------------


class DraftProperty(BaseModel):
    column: str
    name: str
    description: str


class DraftRelationship(BaseModel):
    column: str
    name: str
    description: str


class ConceptDraft(BaseModel):
    type_name: str
    id_prefix: str
    description: str
    standard: str | None = None
    properties: list[DraftProperty]
    relationships: list[DraftRelationship]


async def _model_draft(summary: dict[str, Any], catalog: Catalog, client_factory: Any, model: str | None) -> dict[str, Any] | None:
    cache_key = hashlib.sha256(json.dumps(summary, sort_keys=True, default=str).encode()).hexdigest()
    cached = _cached(f"concept-{cache_key}")
    if cached is not None:
        return cached
    if offline() or not client_factory or not model:
        return None
    prompt = (
        "You maintain an upstream oil and gas M&A data-room ontology. A new spreadsheet brings a concept the catalog lacks.\n"
        f"Existing entity types: {', '.join(t.name for t in catalog.entity_types)}.\n"
        "Naming conventions: entity types are singular PascalCase nouns (Well, LeaseholdTract); properties and measures are snake_case; "
        "relationships are UPPER_SNAKE verbs (IN_COUNTY, OPERATED_BY). Prefer OSDU master-data names when one fits (for example "
        "'OSDU master-data--Well'); otherwise leave standard empty.\n"
        f"Dataset:\n{json.dumps(summary, indent=1, default=str)}\n"
        "Return the entity type name, a short id_prefix, a one-sentence description, an optional standard, one property name and description "
        "per listed property column (numeric measure columns included), and one relationship name and description per listed link column."
    )
    from agent_framework import Message

    try:
        response = await client_factory(model).get_response([Message("user", [prompt])], options={"response_format": ConceptDraft})
        parsed = response.value or ConceptDraft.model_validate_json(response.text)
    except Exception:  # noqa: BLE001 - fall back to the offline draft
        return None
    draft = parsed.model_dump()
    _store(f"concept-{cache_key}", draft)
    return draft


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def proposal_id(dataset_id: str, headers: list[str]) -> str:
    return "mp-" + hashlib.sha256(json.dumps([dataset_id, headers]).encode()).hexdigest()[:10]


async def discover_concepts(room_id: str, silver: Silver, gold: Gold, catalog: Catalog, proposals: list[dict[str, Any]], client_factory: Any = None, model: str | None = None) -> list[dict[str, Any]]:
    """Write a model proposal for every unknown file whose columns the catalog cannot place; return all proposals of the room."""
    roles = {f["path"]: f.get("role") for f in silver.manifest["files"]}
    kinds = key_targets(catalog)
    keys = entity_keys(gold, catalog)
    for dataset_id, table in silver.tables.items():
        if table["family"] != "generic" or roles.get(table["file"]) is not None or not table["headers"]:
            continue
        records = silver.records(dataset_id)
        if not records:
            continue
        headers = [path[-1] for path in table["headers"].values()]
        pid = proposal_id(dataset_id, headers)
        if get_proposal(room_id, pid) is not None:
            continue  # keep the proposal and its decision across rebuilds
        proposal = await _propose(room_id, pid, dataset_id, table, records, catalog, proposals, kinds, keys, client_factory, model)
        if proposal:
            save_proposal(room_id, proposal)
    return list_proposals(room_id)


async def _propose(room_id: str, pid: str, dataset_id: str, table: dict[str, Any], records: list[Any], catalog: Catalog, proposals: list[dict[str, Any]], kinds: dict[str, str], keys: dict[str, dict[str, str]], client_factory: Any, model: str | None) -> dict[str, Any] | None:
    columns = list(table["headers"])
    headers = {column: path[-1] for column, path in table["headers"].items()}
    profiles = column_profiles(records, columns)
    mine = [p for p in proposals if p["dataset_id"] == dataset_id and p["status"] != "rejected"]
    placed = {p["column"] for p in mine}
    key = next((p for p in mine if p["kind"] == "key"), None)
    month = next((p["column"] for p in mine if p["kind"] == "dimension"), None)
    existing_types = {t.name for t in catalog.entity_types}
    existing_prefixes = {t.id_prefix for t in catalog.entity_types}
    existing_rels = {r.name for r in catalog.relationship_types}
    declared = {(r.source, r.target) for r in catalog.relationship_types}
    now = datetime.now(timezone.utc).isoformat()
    base = {"proposal_id": pid, "room_id": room_id, "dataset_id": dataset_id, "file": table["file"], "sheet": table["sheet"], "rows": len(records), "status": "proposed", "created_at": now, "decided_by": None, "decided_at": None, "reason": None}

    def link_candidates(skip: set[str]) -> list[dict[str, Any]]:
        found = []
        for column in columns:
            if column in skip:
                continue
            best = overlaps(profiles[column], keys, kinds, header_key(headers[column]))
            if best:
                target, rate, hits, total = best[0]
                found.append({"column": column, "header": headers[column], "target_type": target.split(".")[0], "target_key": target, "rate": rate, "hits": hits, "total": total})
        return found

    def evidence(link: dict[str, Any]) -> str:
        return f"{link['hits']}/{link['total']} values match" if link["hits"] else f"named by its header; no {link['target_type']} in the room yet"

    if key:
        # The rows describe an existing type: anything the catalog cannot place extends that type.
        subject = key["target"].split(".")[0]
        unplaced = [c for c in columns if c not in placed]
        if not unplaced:
            return None
        items: list[dict[str, Any]] = []
        mappings: list[dict[str, Any]] = []
        links = {c["column"]: c for c in link_candidates(placed) if c["target_type"] != subject}
        for column in unplaced:
            header = headers[column]
            if column in links:
                target_type = links[column]["target_type"]
                if (subject, target_type) in declared:
                    continue  # propose() already offered the declared relationship as a mapping
                name = relationship_name(subject, target_type, existing_rels | {i["relationship"]["name"] for i in items if i["op"] == "add_relationship"})
                items.append({"op": "add_relationship", "relationship": RelationshipType(name=name, source=subject, target=target_type, method="source", build_rule=f"{header} column of {Path(table['file']).name} matched to {links[column]['target_key']} after normalization ({evidence(links[column])})").model_dump(mode="json")})
                items.append({"op": "add_header_rule", "rule": {"pattern": f"^{re.escape(header_key(header))}$", "target": f"{subject}.{name}", "kind": "link"}})
                mappings.append({"column": column, "header": header, "target": f"{subject}.{name}", "kind": "link"})
                continue
            profile = profiles[column]
            if profile["numeric"]:
                name = snake(header)
                items.append({"op": "add_measure", "measure": MeasureDef(name=name, subject=subject, unit=_unit_of(header), dimensions=["month"] if month else [], description=f"{header} from {Path(table['file']).name}").model_dump(mode="json")})
                mappings.append({"column": column, "header": header, "target": f"{subject}.{name}", "kind": "measure"})
            else:
                name = snake(header)
                items.append({"op": "add_property", "entity_type": subject, "property": PropertyDef(name=name, type=_value_type(profile["values"]), description=f"{header} from {Path(table['file']).name}").model_dump(mode="json")})
                mappings.append({"column": column, "header": header, "target": f"{subject}.{name}", "kind": "property"})
            items.append({"op": "add_header_rule", "rule": {"pattern": f"^{re.escape(header_key(header))}$", "target": f"{subject}.{name}", "kind": mappings[-1]["kind"]}})
        if not mappings:
            return None
        return {
            **base,
            "kind": "extend_entity",
            "subject": subject,
            "method": "rule",
            "title": f"Extend {subject} with {len(mappings)} field{'s' if len(mappings) != 1 else ''} from {Path(table['file']).name}",
            "summary": f"The rows are {subject} records ({key['rationale']}). {len(mappings)} column{'s' if len(mappings) != 1 else ''} fit no existing {subject} property or measure: " + ", ".join(m["header"] for m in mappings) + ".",
            "items": items,
            "mappings": mappings,
            "evidence": {"key": {k: key[k] for k in ("column", "header", "target", "confidence", "rationale")}, "links": [links[c] for c in unplaced if c in links]},
        }

    # No existing key matches: find the column that identifies the rows. Text columns qualify; a column of
    # whole numbers only when its header says it is an identifier (a unique measure is not a key).
    links = {c["column"]: c for c in link_candidates(placed)}
    identifiers = [
        c for c in columns
        if c not in placed and c not in links and profiles[c]["values"] and profiles[c]["distinct_ratio"] >= 0.95 and profiles[c]["null_rate"] <= 0.05
        and (_value_type(profiles[c]["values"]) == "string" or (_value_type(profiles[c]["values"]) == "integer" and ID_WORDS.search(f" {header_key(headers[c])} ")))
    ]
    identifiers.sort(key=lambda c: (not ID_WORDS.search(f" {header_key(headers[c])} "), columns.index(c)))
    if not identifiers:
        if len({c["target_type"] for c in links.values()}) >= 2:
            # A crosswalk between two existing types.
            first, second = sorted(links.values(), key=lambda c: -c["rate"])[:2]
            if (first["target_type"], second["target_type"]) in declared or (second["target_type"], first["target_type"]) in declared:
                return None  # propose() binds declared relationships through ordinary mappings
            name = relationship_name(first["target_type"], second["target_type"], existing_rels)
            items = [
                {"op": "add_relationship", "relationship": RelationshipType(name=name, source=first["target_type"], target=second["target_type"], method="crosswalk", build_rule=f"{Path(table['file']).name}: {first['header']} to {second['header']} ({first['hits']}/{first['total']} and {second['hits']}/{second['total']} values match)").model_dump(mode="json")},
                {"op": "add_header_rule", "rule": {"pattern": f"^{re.escape(header_key(first['header']))}$", "target": first["target_key"], "kind": "key"}},
                {"op": "add_header_rule", "rule": {"pattern": f"^{re.escape(header_key(second['header']))}$", "target": f"{first['target_type']}.{name}", "kind": "link"}},
            ]
            return {
                **base, "kind": "link_table", "subject": first["target_type"], "method": "rule",
                "title": f"Link {first['target_type']} to {second['target_type']} from {Path(table['file']).name}",
                "summary": f"The file is a crosswalk: {first['header']} values match {first['target_key']} ({first['hits']}/{first['total']}) and {second['header']} values match {second['target_key']} ({second['hits']}/{second['total']}). The catalog declares no relationship between the two types.",
                "items": items,
                "mappings": [{"column": first["column"], "header": first["header"], "target": first["target_key"], "kind": "key"}, {"column": second["column"], "header": second["header"], "target": f"{first['target_type']}.{name}", "kind": "link"}],
                "evidence": {"links": list(links.values())},
            }
        return None

    key_column = identifiers[0]
    key_header = headers[key_column]
    property_columns = [c for c in columns if c not in placed and c != key_column and c not in links and c != month and not profiles[c]["numeric"] and profiles[c]["values"]]
    measure_columns = [c for c in columns if c not in placed and c != key_column and c not in links and c != month and profiles[c]["numeric"]]
    summary = {
        "file": Path(table["file"]).name, "sheet": table["sheet"], "rows": len(records),
        "key": {"column": key_column, "header": key_header, "samples": profiles[key_column]["values"][:4]},
        "properties": [{"column": c, "header": headers[c], "samples": profiles[c]["values"][:3], "type": _value_type(profiles[c]["values"])} for c in [*property_columns, *measure_columns]],
        "links": [{"column": c["column"], "header": c["header"], "target_type": c["target_type"], "match": evidence(c)} for c in links.values()],
    }
    draft = await _model_draft(summary, catalog, client_factory, model)
    method = "model" if draft else "rule"
    type_name = draft_type_name(table["sheet"], table["file"], key_header, existing_types)
    if draft and re.fullmatch(r"[A-Z][A-Za-z]+", draft.get("type_name") or "") and draft["type_name"] not in existing_types:
        type_name = draft["type_name"]
    prefix = draft_prefix(draft["id_prefix"] if draft and re.fullmatch(r"[a-z][a-z_]*", draft.get("id_prefix") or "") else type_name, existing_prefixes)
    drafted_props = {p["column"]: p for p in (draft or {}).get("properties", [])}
    drafted_rels = {r["column"]: r for r in (draft or {}).get("relationships", [])}

    def prop_name(column: str, header: str, used: set[str]) -> str:
        candidate = drafted_props.get(column, {}).get("name")
        name = candidate if candidate and re.fullmatch(r"[a-z0-9_]+", candidate) else snake(header)
        base_name, counter = name, 2
        while name in used:
            name, counter = f"{base_name}_{counter}", counter + 1
        used.add(name)
        return name

    used_names = {snake(key_header)}
    key_name = snake(key_header)
    properties = [PropertyDef(name=key_name, type=_value_type(profiles[key_column]["values"]), required=True, description=f"{key_header} ({Path(table['file']).name}); forms the entity ID")]
    header_rules = [{"pattern": f"^{re.escape(header_key(key_header))}$", "target": f"{type_name}.{key_name}", "kind": "key"}]
    mappings = [{"column": key_column, "header": key_header, "target": f"{type_name}.{key_name}", "kind": "key"}]
    for column in property_columns:
        header = headers[column]
        name = prop_name(column, header, used_names)
        properties.append(PropertyDef(name=name, type=_value_type(profiles[column]["values"]), description=drafted_props.get(column, {}).get("description") or f"{header} ({Path(table['file']).name})"))
        header_rules.append({"pattern": f"^{re.escape(header_key(header))}$", "target": f"{type_name}.{name}", "kind": "property"})
        mappings.append({"column": column, "header": header, "target": f"{type_name}.{name}", "kind": "property"})
    measures = []
    for column in measure_columns:
        header = headers[column]
        name = prop_name(column, header, used_names)
        measures.append(MeasureDef(name=name, subject=type_name, unit=_unit_of(header), dimensions=["month"] if month else [], description=drafted_props.get(column, {}).get("description") or f"{header} ({Path(table['file']).name})"))
        header_rules.append({"pattern": f"^{re.escape(header_key(header))}$", "target": f"{type_name}.{name}", "kind": "measure"})
        mappings.append({"column": column, "header": header, "target": f"{type_name}.{name}", "kind": "measure"})
    relationships = []
    for column, link in links.items():
        header = headers[column]
        candidate = drafted_rels.get(column, {}).get("name")
        name = candidate if candidate and re.fullmatch(r"[A-Z][A-Z_]+", candidate) and candidate not in existing_rels else relationship_name(type_name, link["target_type"], existing_rels | {r.name for r in relationships})
        relationships.append(RelationshipType(name=name, source=type_name, target=link["target_type"], method="source", build_rule=f"{header} column matched to {link['target_key']} after normalization ({evidence(link)})", description=drafted_rels.get(column, {}).get("description")))
        header_rules.append({"pattern": f"^{re.escape(header_key(header))}$", "target": f"{type_name}.{name}", "kind": "link"})
        mappings.append({"column": column, "header": header, "target": f"{type_name}.{name}", "kind": "link"})
    if month:
        mappings.append({"column": month, "header": headers[month], "target": f"{type_name}.month", "kind": "dimension"})
    entity = EntityType(
        name=type_name, id_prefix=prefix, key=key_name, standard=(draft or {}).get("standard") or None,
        description=(draft or {}).get("description") or f"{type_name} records from {Path(table['file']).name} ({len(records)} rows, keyed by {key_header}).",
        properties=properties,
    )
    items = [
        {"op": "add_entity_type", "entity_type": entity.model_dump(mode="json")},
        *({"op": "add_measure", "measure": m.model_dump(mode="json")} for m in measures),
        *({"op": "add_relationship", "relationship": r.model_dump(mode="json")} for r in relationships),
        *({"op": "add_header_rule", "rule": r} for r in header_rules),
    ]
    link_text = ", ".join(f"{r.target} ({evidence(links[c])})" for r, c in zip(relationships, links)) or "no existing type"
    return {
        **base, "kind": "new_entity", "subject": type_name, "method": method,
        "title": f"New entity type {type_name} from {Path(table['file']).name}",
        "summary": f"No existing entity key matches this file. {key_header} identifies its {len(records)} rows, so a new type {type_name} is proposed with {len(properties) - 1} properties, {len(measures)} measures and links to {link_text}.",
        "items": items,
        "mappings": mappings,
        "evidence": {"key": {"column": key_column, "header": key_header, "distinct_ratio": profiles[key_column]["distinct_ratio"]}, "links": list(links.values()), "draft": "model" if draft else "offline heuristic"},
    }
