"""Field mapping: approved header rules, value-overlap key detection, model proposals, and applying approved mappings."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import yaml
from pydantic import BaseModel

from ..config import cache_dirs, offline
from ..contracts import Catalog, RuleSet
from .build import Gold, Silver
from .catalog import catalog_dir

KEY_TARGETS = {"Well.api_14": "api", "Well.api_10": "api10", "EconomicLocation.inpt_id": "text", "Unit.name": "name"}
OFFLINE_KEYWORDS = [("oil", "oil_bbl"), ("gas", "gas_mcf"), ("water", "water_bbl"), ("day", "days_on")]


def header_key(header: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", header.lower()).split())


def load_header_rules() -> list[dict[str, Any]]:
    return yaml.safe_load((catalog_dir() / "header_rules.yaml").read_text("utf-8"))["rules"]


def allowed_targets(catalog: Catalog, subject: str) -> dict[str, str]:
    entity = catalog.entity(subject)
    targets = {f"{subject}.{p.name}": f"property ({p.type}{', ' + p.unit if p.unit else ''})" for p in entity.properties}
    for measure in catalog.measures:
        if measure.subject == subject:
            targets[f"{subject}.{measure.name}"] = f"measure ({measure.unit}): {measure.description}"
            for dimension in measure.dimensions:
                targets[f"{subject}.{dimension}"] = "dimension"
    return targets


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
    return str(value).strip()


def entity_keys(gold: Gold) -> dict[str, dict[str, str]]:
    keys: dict[str, dict[str, str]] = {target: {} for target in KEY_TARGETS}
    for node in gold.nodes.values():
        props = node["props"]
        if node["type"] == "Well":
            keys["Well.api_14"][props["api_14"]] = node["id"]
            if props.get("api_10"):
                keys["Well.api_10"][props["api_10"]] = node["id"]
        elif node["type"] == "EconomicLocation":
            keys["EconomicLocation.inpt_id"][props["inpt_id"]] = node["id"]
        elif node["type"] == "Unit":
            keys["Unit.name"][_normalize_key(node["label"], "name")] = node["id"]
    return keys


class ProposedMapping(BaseModel):
    column: str
    target: str
    confidence: float
    rationale: str


class MappingProposals(BaseModel):
    mappings: list[ProposedMapping]


async def propose(silver: Silver, gold: Gold, catalog: Catalog, decisions: dict[tuple[str, str], dict[str, Any]], client_factory: Any = None, model: str | None = None) -> list[dict[str, Any]]:
    """Mapping proposals for every tabular field: rules first, then key overlap, then the model."""
    rules = [(re.compile(rule["pattern"]), rule) for rule in load_header_rules()]
    keys = entity_keys(gold)
    proposals: list[dict[str, Any]] = []
    for dataset_id, table in silver.tables.items():
        records = silver.records(dataset_id) if table["family"] == "generic" else []
        fields = []
        for column, path in table["headers"].items():
            header = path[-1]
            item = {"dataset_id": dataset_id, "file": table["file"], "field_id": f"{dataset_id}/{column}", "column": column, "header": header, "header_key": header_key(header)}
            fields.append(item)
            for pattern, rule in rules:
                if pattern.search(item["header_key"]):
                    proposals.append({**item, "target": rule["target"], "kind": rule["kind"], "transform": rule.get("transform"), "method": "rule", "status": "approved", "confidence": 1.0, "rationale": f"header rule /{rule['pattern']}/"})
                    break
        if table["family"] != "generic" or not records:
            continue
        mapped = {p["column"] for p in proposals if p["dataset_id"] == dataset_id}
        for item in fields:
            if item["column"] in mapped:
                continue
            values = [values.get(item["column"]) for _, values, _ in records]
            for target, kind in KEY_TARGETS.items():
                normalized = [_normalize_key(v, kind) for v in values if v not in (None, "")]
                hits = sum(1 for v in normalized if v in keys[target])
                if normalized and hits / len(normalized) >= 0.5:
                    proposals.append({**item, "target": target, "kind": "key", "method": "rule", "status": "proposed", "confidence": round(hits / len(normalized), 3), "match_rate": f"{hits}/{len(normalized)}", "rationale": f"value overlap: {hits} of {len(normalized)} values match existing {target} after normalization"})
                    mapped.add(item["column"])
                    break
        key = next((p for p in proposals if p["dataset_id"] == dataset_id and p["kind"] == "key"), None)
        if not key:
            continue
        subject = key["target"].split(".")[0]
        for proposal in proposals:
            if proposal["dataset_id"] == dataset_id and proposal["target"].startswith("*."):
                proposal["target"] = f"{subject}.{proposal['target'][2:]}"
        remaining = [item for item in fields if item["column"] not in mapped]
        if remaining:
            proposals.extend(await _model_proposals(remaining, records, subject, catalog, client_factory, model))
    for proposal in proposals:
        remembered = decisions.get((proposal["header_key"], proposal["target"]))
        if remembered and proposal["status"] != "approved":
            proposal.update({"status": remembered["status"], "decided_by": remembered.get("decided_by"), "remembered": True})
    return [p for p in proposals if not p["target"].startswith("*.")]


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
            kind = "dimension" if targets[item["target"]] == "dimension" else "measure" if targets[item["target"]].startswith("measure") else "property"
            proposals.append({**by_column[item["column"]], "target": item["target"], "kind": kind, "method": method, "status": "proposed", "confidence": round(float(item["confidence"]), 2), "rationale": item["rationale"]})
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


def apply_approved(silver: Silver, gold: Gold, proposals: list[dict[str, Any]], rules: RuleSet, catalog: Catalog) -> list[dict[str, Any]]:
    """Turn approved mappings of generic datasets into facts; unmatched keys become issues."""
    keys = entity_keys(gold)
    unit_of = {(m.subject, m.name): m.unit for m in catalog.measures}
    issues = []
    for dataset_id, table in silver.tables.items():
        if table["family"] != "generic":
            continue
        approved = [p for p in proposals if p["dataset_id"] == dataset_id and p["status"] == "approved"]
        key = next((p for p in approved if p["kind"] == "key"), None)
        measures = [p for p in approved if p["kind"] == "measure"]
        if not key or not measures:
            continue
        month = next((p for p in approved if p["kind"] == "dimension" and p["target"].endswith(".month")), None)
        kind = KEY_TARGETS[key["target"]]
        unmatched: list[str] = []
        for row, values, _ in silver.records(dataset_id):
            raw = values.get(key["column"])
            entity = keys[key["target"]].get(_normalize_key(raw, kind))
            if entity is None:
                if raw not in (None, ""):
                    unmatched.append(str(raw))
                continue
            for mapping in measures:
                value = values.get(mapping["column"])
                if isinstance(value, (int, float)):
                    subject, measure = mapping["target"].split(".")
                    gold.fact(entity, measure, float(value), unit_of.get((subject, measure), ""), table["file"], f"{table['sheet']}!{mapping['column']}{row}", period=str(values.get(month["column"]))[:10] if month else None, dataset_id=dataset_id)
        if unmatched:
            rule = rules.get("UNMATCHED_KEY")
            issues.append(
                {
                    "issue_id": f"issue:unmatched-key:{gold.context['asset']}:{dataset_id.replace('/', '-')}",
                    "rule": "UNMATCHED_KEY", "severity": rule.severity, "subject": gold.context["asset"], "qualifier": dataset_id,
                    "detail": f"{len(unmatched)} rows of {table['file']} have {key['header']} values that match no {key['target']} (e.g. {', '.join(sorted(set(unmatched))[:3])})",
                    "assertions": [{"label": key["header"], "value": sorted(set(unmatched))[:10], "file": table["file"], "locator": f"{table['sheet']}!{key['column']}"}, {"label": key["target"], "value": None}],
                    "blocks": rule.blocks, "count": len(unmatched),
                }
            )
    return issues
