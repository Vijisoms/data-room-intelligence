"""Field mapping: header rules, value-overlap key and link detection, model proposals, and the generic recipe
that turns approved mappings into entities, properties, links and facts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

import yaml
from pydantic import BaseModel

from ..config import cache_dirs, offline, slug
from ..contracts import Catalog, RuleSet
from .build import Gold, Silver
from .catalog import catalog_dir

OFFLINE_KEYWORDS = [("oil", "oil_bbl"), ("gas", "gas_mcf"), ("water", "water_bbl"), ("day", "days_on")]
OVERLAP_THRESHOLD = 0.5
KEY_UNIQUENESS = 0.9


def header_key(header: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", header.lower()).split())


def load_header_rules() -> list[dict[str, Any]]:
    return yaml.safe_load((catalog_dir() / "header_rules.yaml").read_text("utf-8"))["rules"]


def key_kind(property_name: str) -> str:
    """How values of a key property are normalized before comparison (see HOW_IT_WORKS section 5)."""
    if property_name == "api_14":
        return "api"
    if property_name == "api_10":
        return "api10"
    if property_name == "name":
        return "name"
    if property_name == "code":
        return "code"
    return "text"


def key_targets(catalog: Catalog) -> dict[str, str]:
    """Every entity type's key as `Type.key` -> normalization kind, plus Well.api_10 as an alternate key."""
    targets = {f"{t.name}.{t.key}": key_kind(t.key) for t in catalog.entity_types}
    if any(t.name == "Well" and any(p.name == "api_10" for p in t.properties) for t in catalog.entity_types):
        targets["Well.api_10"] = "api10"
    return targets


def allowed_targets(catalog: Catalog, subject: str) -> dict[str, str]:
    entity = catalog.entity(subject)
    targets = {f"{subject}.{p.name}": f"property ({p.type}{', ' + p.unit if p.unit else ''})" for p in entity.properties}
    for measure in catalog.measures:
        if measure.subject == subject:
            targets[f"{subject}.{measure.name}"] = f"measure ({measure.unit}): {measure.description}"
            for dimension in measure.dimensions:
                targets[f"{subject}.{dimension}"] = "dimension"
    for rel in catalog.relationship_types:
        if rel.source == subject:
            targets[f"{subject}.{rel.name}"] = f"link to {rel.target} ({rel.method}): {rel.build_rule}"
    return targets


def target_kind(catalog: Catalog, target: str) -> str:
    description = allowed_targets(catalog, target.split(".")[0]).get(target, "")
    return "dimension" if description == "dimension" else "measure" if description.startswith("measure") else "link" if description.startswith("link") else "property"


def _normalize_key(value: Any, kind: str) -> str | None:
    if value in (None, ""):
        return None
    if kind in {"api", "api10"}:
        digits = re.sub(r"\D", "", str(value).split(".")[0] if isinstance(value, float) else str(value))
        if kind == "api10":
            return digits[:10] if len(digits) >= 10 else None
        return digits.ljust(14, "0") if len(digits) in (10, 12, 14) else None
    if kind == "name":
        return " ".join(str(value).upper().replace("_", " ").split())
    if kind == "code":
        return str(value).strip().upper()
    text = str(value).strip()
    return text[:-2] if isinstance(value, float) and text.endswith(".0") else text


def entity_keys(gold: Gold, catalog: Catalog) -> dict[str, dict[str, str]]:
    """Normalized key value -> entity ID for every key target, from the nodes built so far."""
    kinds = key_targets(catalog)
    key_prop = {t.name: t.key for t in catalog.entity_types}
    keys: dict[str, dict[str, str]] = {target: {} for target in kinds}
    for node in gold.nodes.values():
        type_ = node["type"]
        if type_ not in key_prop:
            continue
        target = f"{type_}.{key_prop[type_]}"
        value = node["props"].get(key_prop[type_], node["label"] if key_kind(key_prop[type_]) == "name" else node["key"])
        normalized = _normalize_key(value, kinds[target])
        if normalized:
            keys[target].setdefault(normalized, node["id"])
        if type_ == "Well" and node["props"].get("api_10"):
            keys["Well.api_10"].setdefault(node["props"]["api_10"], node["id"])
    return keys


def column_profiles(records: list[Any], columns: list[str]) -> dict[str, dict[str, Any]]:
    """Per column: non-null values, distinct ratio and null rate (shared by mapping and concept discovery)."""
    profiles = {}
    for column in columns:
        values = [values.get(column) for _, values, _ in records]
        present = [v for v in values if v not in (None, "")]
        distinct = {str(v) for v in present}
        profiles[column] = {
            "values": present,
            "null_rate": round(1 - len(present) / len(records), 4) if records else 1.0,
            "distinct_ratio": round(len(distinct) / len(present), 4) if present else 0.0,
            "distinct": len(distinct),
            "numeric": bool(present) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present),
        }
    return profiles


# Headers that name a base type's key. They matter when the room has no entities of that type yet (a new
# project whose first file is a lease schedule): the type is recognised from the header, and the rows link
# up once the entities arrive. API columns must also hold API-shaped numbers.
HEADER_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(api|api ?14|api ?number|api ?no|api ?num|well api)$"), "Well.api_14"),
    (re.compile(r"^(unit|unit name|dsu|spacing unit|drilling unit)$"), "Unit.name"),
    (re.compile(r"^(county|county parish|parish)$"), "County.name"),
    (re.compile(r"^(operator|current operator|operator name)$"), "Operator.name"),
    (re.compile(r"^(battery|battery code|battery id|ctb|ctb code)$"), "BatteryCode.code"),
    (re.compile(r"^(facility|sales facility|pricing facility|facility name|tank battery)$"), "PricingFacility.name"),
    (re.compile(r"^(inpt id|location id)$"), "EconomicLocation.inpt_id"),
]


def header_hint(header_key_: str, values: list[Any], kinds: dict[str, str]) -> tuple[str, float] | None:
    for pattern, target in HEADER_HINTS:
        if target in kinds and pattern.search(header_key_):
            normalized = [_normalize_key(v, kinds[target]) for v in values]
            rate = sum(1 for v in normalized if v) / len(values) if values else 0.0
            if rate >= OVERLAP_THRESHOLD:
                return target, round(rate, 3)
    return None


def overlaps(profile: dict[str, Any], keys: dict[str, dict[str, str]], kinds: dict[str, str], header_key_: str | None = None) -> list[tuple[str, float, int, int]]:
    """Key targets this column points at, best first: (target, rate, hits, total).

    Values are compared with the existing entities' keys. When no type has matching entities but the header
    names a base type (see HEADER_HINTS), that type is returned with hits = 0: known by name, not yet by value."""
    found = []
    for target, kind in kinds.items():
        normalized = [_normalize_key(v, kind) for v in profile["values"]]
        normalized = [v for v in normalized if v]
        if not normalized or not keys.get(target):
            continue
        hits = sum(1 for v in normalized if v in keys[target])
        rate = hits / len(normalized)
        if rate >= OVERLAP_THRESHOLD:
            found.append((target, round(rate, 3), hits, len(normalized)))
    if not found and header_key_:
        hint = header_hint(header_key_, profile["values"], kinds)
        if hint and not keys.get(hint[0]):
            found.append((hint[0], hint[1], 0, len(profile["values"])))
    # Ties go to a type's primary key (Well.api_14 over the alternate Well.api_10).
    return sorted(found, key=lambda item: (-item[1], item[0].endswith(".api_10"), item[0]))


def overlap_rationale(target: str, rate: float, hits: int, total: int) -> str:
    if hits == 0:
        return f"header names {target}; the room has no {target.split('.')[0]} entities yet to compare values with, so rows link up when they arrive"
    return f"value overlap: {hits} of {total} values match existing {target} after normalization"


class ProposedMapping(BaseModel):
    column: str
    target: str
    confidence: float
    rationale: str


class MappingProposals(BaseModel):
    mappings: list[ProposedMapping]


async def propose(
    silver: Silver, gold: Gold, catalog: Catalog, decisions: dict[tuple[str, str], dict[str, Any]], client_factory: Any = None, model: str | None = None, header_rules: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Mapping proposals for every tabular field: header rules first, then key and link overlap, then the model."""
    rules = [(re.compile(rule["pattern"]), rule) for rule in (header_rules or load_header_rules())]
    kinds = key_targets(catalog)
    keys = entity_keys(gold, catalog)
    relationships = {(r.source, r.target): r for r in catalog.relationship_types}
    proposals: list[dict[str, Any]] = []
    def by_rule(item: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
        return {**item, "target": rule["target"], "kind": rule["kind"], "transform": rule.get("transform"), "method": "rule", "status": "approved", "confidence": 1.0, "rationale": f"header rule /{rule['pattern']}/"}

    for dataset_id, table in silver.tables.items():
        generic = table["family"] == "generic"
        records = silver.records(dataset_id) if generic else []
        fields = []
        for column, path in table["headers"].items():
            header = path[-1]
            item = {"dataset_id": dataset_id, "file": table["file"], "field_id": f"{dataset_id}/{column}", "column": column, "header": header, "header_key": header_key(header)}
            fields.append(item)
            for pattern, rule in rules:
                if not pattern.search(item["header_key"]):
                    continue
                # Known layouts take every rule as a label. An unknown table takes only the rules that identify its
                # rows (keys and dimensions) here; the other rules apply once the subject type is known, so a "Unit"
                # column in a lease schedule is not labelled as the economics file's unit column.
                if not generic or rule["kind"] == "key" or rule["target"].startswith("*."):
                    proposals.append(by_rule(item, rule))
                    break
        if not generic or not records:
            continue
        mapped = {p["column"] for p in proposals if p["dataset_id"] == dataset_id}
        profiles = column_profiles(records, [f["column"] for f in fields])
        month = next((p["column"] for p in proposals if p["dataset_id"] == dataset_id and p["kind"] == "dimension"), None)
        # Key: a column whose values match an existing entity key and that identifies the row (alone or with the month dimension).
        key = next((p for p in proposals if p["dataset_id"] == dataset_id and p["kind"] == "key"), None)
        if not key:
            candidates = []
            for item in fields:
                if item["column"] in mapped:
                    continue
                profile = profiles[item["column"]]
                for target, rate, hits, total in overlaps(profile, keys, kinds, item["header_key"]):
                    if _identifies_rows(records, item["column"], month, profile):
                        candidates.append((rate, -fields.index(item), item, target, hits, total))
                        break
            if candidates:
                rate, _, item, target, hits, total = max(candidates)
                key = {**item, "target": target, "kind": "key", "transform": None, "method": "rule", "status": "proposed", "confidence": round(rate, 3), "match_rate": f"{hits}/{total}" if hits else None, "rationale": overlap_rationale(target, rate, hits, total)}
                proposals.append(key)
                mapped.add(item["column"])
        if not key:
            continue
        subject = key["target"].split(".")[0]
        for proposal in proposals:
            if proposal["dataset_id"] == dataset_id and proposal["target"].startswith("*."):
                proposal["target"] = f"{subject}.{proposal['target'][2:]}"
        for item in fields:
            if item["column"] in mapped:
                continue
            rule = next((rule for pattern, rule in rules if rule["target"].startswith(f"{subject}.") and pattern.search(item["header_key"])), None)
            if rule:
                proposals.append(by_rule(item, rule))
                mapped.add(item["column"])
        # Links: other columns whose values match another type's key, when the catalog declares that relationship.
        for item in fields:
            if item["column"] in mapped:
                continue
            for target, rate, hits, total in overlaps(profiles[item["column"]], keys, kinds, item["header_key"]):
                other = target.split(".")[0]
                rel = relationships.get((subject, other))
                if rel is None or other == subject:
                    continue
                proposals.append({**item, "target": f"{subject}.{rel.name}", "kind": "link", "transform": None, "method": "rule", "status": "proposed", "confidence": round(rate, 3), "match_rate": f"{hits}/{total}" if hits else None, "rationale": f"{overlap_rationale(target, rate, hits, total)}; feeds {rel.name} ({rel.method})"})
                mapped.add(item["column"])
                break
        remaining = [item for item in fields if item["column"] not in mapped]
        if remaining:
            proposals.extend(await _model_proposals(remaining, records, subject, catalog, client_factory, model))
    for proposal in proposals:
        remembered = decisions.get((proposal["header_key"], proposal["target"]))
        if remembered and proposal["status"] != "approved":
            proposal.update({"status": remembered["status"], "decided_by": remembered.get("decided_by"), "remembered": True})
    return [p for p in proposals if not p["target"].startswith("*.")]


def _identifies_rows(records: list[Any], column: str, month: str | None, profile: dict[str, Any]) -> bool:
    if profile["distinct_ratio"] >= KEY_UNIQUENESS:
        return True
    if month:
        pairs = {(str(values.get(column)), str(values.get(month))) for _, values, _ in records if values.get(column) not in (None, "")}
        return len(pairs) >= KEY_UNIQUENESS * len(profile["values"])
    return False


async def _model_proposals(fields: list[dict[str, Any]], records: list[Any], subject: str, catalog: Catalog, client_factory: Any, model: str | None) -> list[dict[str, Any]]:
    targets = allowed_targets(catalog, subject)
    profiles = [{"column": f["column"], "header": f["header"], "samples": [values.get(f["column"]) for _, values, _ in records[:4]]} for f in fields]
    cache_key = hashlib.sha256(json.dumps([profiles, sorted(targets)], sort_keys=True, default=str).encode()).hexdigest()
    result = _cached(cache_key)
    method = "model"
    if result is None and not offline() and client_factory and model:
        prompt = (
            f"Map spreadsheet columns to an upstream oil and gas ontology. The rows describe {subject} entities.\n"
            f"Allowed targets (use exactly one, or 'none' when nothing fits):\n{json.dumps(targets, indent=1)}\n"
            f"Columns with sample values:\n{json.dumps(profiles, default=str)}\n"
            "Return one mapping per column with a confidence from 0 to 1 and a one-sentence rationale."
        )
        from agent_framework import Message

        response = await client_factory(model).get_response([Message("user", [prompt])], options={"response_format": MappingProposals})
        parsed = response.value or MappingProposals.model_validate_json(response.text)
        result = [item.model_dump() for item in parsed.mappings]
        _store(cache_key, result)
    if result is None:
        method = "rule"
        result = []
        for field in fields:
            words = field["header_key"]
            target = next((f"{subject}.{measure}" for word, measure in OFFLINE_KEYWORDS if word in words and f"{subject}.{measure}" in targets), "none")
            result.append({"column": field["column"], "target": target, "confidence": 0.6, "rationale": "keyword heuristic (offline; the model proposes these when online)"})
    by_column = {f["column"]: f for f in fields}
    proposals = []
    for item in result:
        if item["column"] in by_column and item["target"] in targets:
            description = targets[item["target"]]
            kind = "dimension" if description == "dimension" else "measure" if description.startswith("measure") else "link" if description.startswith("link") else "property"
            proposals.append({**by_column[item["column"]], "target": item["target"], "kind": kind, "transform": None, "method": method, "status": "proposed", "confidence": round(float(item["confidence"]), 2), "rationale": item["rationale"]})
    return proposals


def _cached(key: str) -> Any:
    for root in cache_dirs():
        path = root / "mapping" / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text("utf-8"))
    return None


def _store(key: str, value: Any) -> None:
    path = cache_dirs()[0] / "mapping" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _transformed(value: Any, transform: str | None) -> Any:
    if transform and transform.startswith("divide:") and isinstance(value, (int, float)):
        return float(value) / float(transform.split(":")[1])
    return value


def apply_approved(silver: Silver, gold: Gold, proposals: list[dict[str, Any]], rules: RuleSet, catalog: Catalog) -> list[dict[str, Any]]:
    """The generic recipe. For each generic dataset with an approved key mapping:

    - rows whose key matches an existing entity attach properties, links and facts to it;
    - when the subject type has no entities yet (a type added for this project, or a base type the room's
      files never produced), each row creates one, keyed and cited like any other entity;
    - approved link mappings create relationships declared in the catalog, resolved by the target's key;
    - keys and link values that match nothing raise UNMATCHED_KEY / UNMATCHED_LINK instead of being dropped.
    """
    kinds = key_targets(catalog)
    keys = entity_keys(gold, catalog)
    key_prop = {t.name: t.key for t in catalog.entity_types}
    prefixes = {t.name: t.id_prefix for t in catalog.entity_types}
    relationships = {(r.source, r.name): r for r in catalog.relationship_types}
    unit_of = {(m.subject, m.name): m.unit for m in catalog.measures}
    existing_types = {n["type"] for n in gold.nodes.values()}
    asset = gold.context["asset"]
    issues = []
    for dataset_id, table in silver.tables.items():
        if table["family"] != "generic":
            continue
        approved = [p for p in proposals if p["dataset_id"] == dataset_id and p["status"] == "approved"]
        key = next((p for p in approved if p["kind"] == "key"), None)
        if not key:
            continue
        subject, key_name = key["target"].split(".")
        if subject not in prefixes:
            continue
        kind = kinds.get(key["target"], "text")
        creates = subject not in existing_types
        properties = [p for p in approved if p["kind"] == "property"]
        measures = [p for p in approved if p["kind"] == "measure"]
        links = [p for p in approved if p["kind"] == "link" and (subject, p["target"].split(".")[1]) in relationships]
        month = next((p for p in approved if p["kind"] == "dimension" and p["target"].endswith(".month")), None)
        label_column = next((p["column"] for p in properties if re.search(r"name|title|label|description", p["target"].split(".")[1])), None)
        sheet = table["sheet"]
        file = table["file"]
        unmatched: list[str] = []
        unmatched_links: dict[str, list[str]] = defaultdict(list)
        seen_edges: set[tuple[str, str, str]] = set()
        for row, values, _ in silver.records(dataset_id):
            raw = values.get(key["column"])
            normalized = _normalize_key(raw, kind)
            if normalized is None:
                continue
            entity = keys[key["target"]].get(normalized)
            locator = f"{sheet}!{key['column']}{row}"
            if entity is None:
                if not creates:
                    unmatched.append(str(raw))
                    continue
                node_key = normalized if kind in {"api", "api10"} else slug(normalized)
                label = values.get(label_column) if label_column else None
                stored_key = normalized if kind in {"api", "api10", "code"} else str(raw).strip()
                entity = gold.node(subject, prefixes[subject], node_key, label or stored_key, file, locator, **{key_name: stored_key})
                keys[key["target"]][normalized] = entity
            props = gold.nodes[entity]["props"]
            for mapping in properties:
                value = values.get(mapping["column"])
                name = mapping["target"].split(".")[1]
                if value not in (None, "") and name not in props:
                    props[name] = _transformed(value, mapping.get("transform"))
            for mapping in measures:
                value = values.get(mapping["column"])
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    measure = mapping["target"].split(".")[1]
                    gold.fact(entity, measure, float(_transformed(value, mapping.get("transform"))), unit_of.get((subject, measure), ""), file, f"{sheet}!{mapping['column']}{row}", period=str(values.get(month["column"]))[:10] if month else None, dataset_id=dataset_id)
            for mapping in links:
                rel = relationships[(subject, mapping["target"].split(".")[1])]
                raw_link = values.get(mapping["column"])
                target_key = f"{rel.target}.{key_prop[rel.target]}"
                target = keys.get(target_key, {}).get(_normalize_key(raw_link, kinds.get(target_key, "text")) or "")
                if target is None:
                    if raw_link not in (None, ""):
                        unmatched_links[rel.name].append(str(raw_link))
                    continue
                if (rel.name, entity, target) in seen_edges:
                    continue
                seen_edges.add((rel.name, entity, target))
                gold.edge(entity, rel.name, target, rel.method, file, f"{sheet}!{mapping['column']}{row}", source_value=raw_link, dataset_id=dataset_id)
        if unmatched:
            rule = rules.get("UNMATCHED_KEY")
            issues.append(
                {
                    "issue_id": f"issue:unmatched-key:{asset}:{dataset_id.replace('/', '-')}",
                    "rule": "UNMATCHED_KEY", "severity": rule.severity, "subject": asset, "qualifier": dataset_id,
                    "detail": f"{len(unmatched)} rows of {file} have {key['header']} values that match no {key['target']} (e.g. {', '.join(sorted(set(unmatched))[:3])})",
                    "assertions": [{"label": key["header"], "value": sorted(set(unmatched))[:10], "file": file, "locator": f"{sheet}!{key['column']}"}, {"label": key["target"], "value": None}],
                    "blocks": rule.blocks, "count": len(unmatched),
                }
            )
        for rel_name, values_ in unmatched_links.items():
            rule = rules.get("UNMATCHED_LINK")
            mapping = next(p for p in links if p["target"].endswith(f".{rel_name}"))
            rel = relationships[(subject, rel_name)]
            issues.append(
                {
                    "issue_id": f"issue:unmatched-link:{asset}:{dataset_id.replace('/', '-')}:{slug(rel_name)}",
                    "rule": "UNMATCHED_LINK", "severity": rule.severity, "subject": asset, "qualifier": f"{dataset_id} {rel_name}",
                    "detail": f"{len(values_)} rows of {file} have {mapping['header']} values that match no {rel.target} (e.g. {', '.join(sorted(set(values_))[:3])}); no {rel_name} link was created for them",
                    "assertions": [{"label": mapping["header"], "value": sorted(set(values_))[:10], "file": file, "locator": f"{sheet}!{mapping['column']}"}, {"label": f"{rel.target}.{key_prop[rel.target]}", "value": None}],
                    "blocks": rule.blocks, "count": len(values_),
                }
            )
    return issues
