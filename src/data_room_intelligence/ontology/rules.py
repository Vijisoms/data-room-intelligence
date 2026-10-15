"""Reconciliation rules: one issue per conflicting subject, with both assertions cited."""

from __future__ import annotations

import re
from collections import defaultdict
from statistics import mean
from typing import Any

from ..config import slug
from ..contracts import RuleSet
from .build import SELLER_OPERATOR, Gold

TOLERANCE = 1e-6


def evaluate(gold: Gold, rules: RuleSet, extra: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    nodes = gold.nodes
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    inn: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in gold.edges:
        out[edge["source"]].append(edge)
        inn[edge["target"]].append(edge)

    def add(code: str, subject: str, detail: str, assertions: list[dict[str, Any]], qualifier: str | None = None, **extra_fields: Any) -> None:
        rule = rules.get(code)
        issues.append(
            {
                "issue_id": f"issue:{slug(code)}:{subject}" + (f":{slug(qualifier)}" if qualifier else ""),
                "rule": code,
                "severity": rule.severity,
                "subject": subject,
                "qualifier": qualifier,
                "detail": detail,
                "assertions": assertions,
                "blocks": rule.blocks,
                **extra_fields,
            }
        )

    def cite(label: str, value: Any, edge_or_fact: dict[str, Any] | None, entity: str | None = None) -> dict[str, Any]:
        item = edge_or_fact or {}
        return {"label": label, "value": value, "entity": entity, "file": item.get("file"), "locator": item.get("locator")}

    for well, node in nodes.items():
        if node["type"] != "Well":
            continue
        spatial = [edge for edge in out[well] if edge["kind"] == "LATERAL_IN_UNIT"]
        for link in (edge for edge in inn[well] if edge["kind"] == "IS_WELL"):
            assigned = next((edge for edge in out[link["source"]] if edge["kind"] == "ASSIGNED_TO_UNIT"), None)
            if assigned and assigned["target"] not in {edge["target"] for edge in spatial}:
                names = ", ".join(nodes[edge["target"]]["label"] for edge in spatial) or "none"
                add(
                    "UNIT_ASSIGNMENT_CONFLICT", well,
                    f"ComboCurve assigns {nodes[assigned['target']]['label']}; the lateral lies in {names}",
                    [cite("ComboCurve UNIT", nodes[assigned["target"]]["label"], assigned, assigned["target"]),
                     cite("GIS lateral within unit", names, spatial[0] if spatial else None, spatial[0]["target"] if spatial else None)],
                    location=link["source"],
                )

    by_key: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    for fact in gold.facts:
        by_key[(fact["subject"], fact["measure"], fact["zone"] or fact["case_id"])] = fact
    for (subject, measure, zone), fact in list(by_key.items()):
        if measure == "gis_wi":
            book = by_key.get((subject, "operational_wi", zone))
            if book and book["value"] is not None and abs(fact["value"] - book["value"]) > TOLERANCE:
                add("OWNERSHIP_VALUE_CONFLICT", subject, f"{zone}: GIS WI {fact['value']:.4f} vs Unit Details {book['value']:.4f}",
                    [cite("Unit Details operational WI", round(book["value"], 6), book), cite("Unit shapefile WI", round(fact["value"], 6), fact)], qualifier=zone, zone=zone)
        if measure == "dcf10_ky":
            other = by_key.get((subject, "dcf10_mf", zone))
            if other and abs(fact["value"] - other["value"]) > TOLERANCE:
                add("VALUE_FIELD_CONFLICT", subject, f"10% discount cash flow KY {fact['value']:,.1f} vs MF {other['value']:,.1f} (M$)",
                    [cite("ONELINE KY", round(fact["value"], 3), fact), cite("ONELINE MF (same header)", round(other["value"], 3), other)])

    for location, node in nodes.items():
        if node["type"] != "EconomicLocation":
            continue
        if not any(edge["kind"] == "TARGETS_ZONE" for edge in out[location]):
            zone = node["props"].get("landing_zone")
            add("ZONE_ALIAS_MISSING", location, f"Landing zone {zone} has no approved bench",
                [cite("Landing Zone", zone, {"file": node["file"], "locator": node["locator"]}), cite("Bench alias", None, None)])
        for edge in out[location]:
            if edge["kind"] == "OPERATED_BY" and nodes[edge["target"]]["label"] == SELLER_OPERATOR and edge["props"].get("alias") == "NON-OP":
                add("OPERATOR_ALIAS_CONFLICT", location, f"Current Operator {SELLER_OPERATOR} carries the alias NON-OP",
                    [cite("Current Operator", SELLER_OPERATOR, edge), cite("Current Operator Alias", "NON-OP", edge)])
    for battery, node in nodes.items():
        if node["type"] == "BatteryCode" and not any(edge["kind"] == "PRICED_AT" for edge in out[battery]):
            add("CROSSWALK_MISSING", battery, f"{node['label']} has no basis-report pricing facility",
                [cite("Battery code", node["label"], {"file": node["file"], "locator": node["locator"]}), cite("Pricing facility", None, None)])

    uncached: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for fact in gold.facts:
        if fact["quality"] == "uncached_formula":
            uncached[(fact["subject"], fact["item"])].append(fact)
    for (scope, item), facts in uncached.items():
        add("FORMULA_CACHE_MISSING", scope, f"{item}: {len(facts)} monthly formulas have no saved value ({facts[0]['period']} to {facts[-1]['period']})",
            [cite("Formula cells", len(facts), facts[0]), cite("Cached values", None, None)], qualifier=item, count=len(facts))

    computed = claim_metrics(gold)
    for claim_id, node in nodes.items():
        if node["type"] != "DocumentClaim":
            continue
        props = node["props"]
        metric = computed.get(props["label"])
        if metric is None:
            props["check"] = "unverifiable"
            continue
        value, description, sources = metric
        tolerance = _tolerance(props["raw"])
        props.update({"computed": round(value, 4), "computed_from": description})
        props["check"] = "match" if abs(value - props["value"]) <= tolerance else "mismatch"
        if props["check"] == "mismatch":
            add("CLAIM_MISMATCH", claim_id, f"{props['raw']} (page {props['page']}) vs computed {value:,.2f} from {description}",
                [cite("Document claim", props["value"], {"file": node["file"], "locator": node["locator"]}), cite("Computed from the room", round(value, 4), sources)])
    return issues + list(extra or [])


def _tolerance(raw: str) -> float:
    match = re.search(r"(\d[\d,]*)(?:\.(\d+))?\s*%?$", raw.strip())
    decimals = len(match.group(2)) if match and match.group(2) else 0
    return 0.5 * 10**-decimals + 1e-9


def claim_metrics(gold: Gold) -> dict[str, tuple[float, str, dict[str, Any]]]:
    nodes = gold.nodes.values()
    count = lambda type_: sum(n["type"] == type_ for n in nodes)  # noqa: E731
    locations = [n for n in nodes if n["type"] == "EconomicLocation"]
    facts = defaultdict(list)
    for fact in gold.facts:
        facts[fact["measure"]].append(fact)
    wi = [f["value"] for f in facts["wi"]]
    nri = [f["value"] for f in facts["nri"]]
    operated = sum(1 for e in gold.edges if e["kind"] == "OPERATED_BY" and gold.nodes[e["target"]]["label"] == SELLER_OPERATOR)
    wca = [f for f in facts["net_acres"] if f["zone"] == "WCA"]
    ud = {"file": "Lone Star Basin Unit Details_vF_2026.08.06.xlsx", "locator": "Unit Details"}
    oneline = {"file": "Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx", "locator": "ONELINE"}
    metrics = {
        "Drilling Units": (count("Unit"), "Unit Details unit rows", ud),
        "Primary-Bench Net Acres": (sum(f["value"] for f in wca), "Unit Details WCA net acres (P8:P97)", {**ud, "locator": "Unit Details!P8:P97"}),
        "Total Econ Locations": (len(locations), "ComboCurve ONELINE rows", oneline),
        "Counties": (count("County"), "Unit Details counties", ud),
        "Development Areas": (count("DevelopmentArea"), "Unit Details development areas", ud),
        "Gross Acres": (sum(n["props"].get("gross_acres") or 0 for n in nodes if n["type"] == "Unit"), "Unit Details gross acres (H8:H97)", {**ud, "locator": "Unit Details!H8:H97"}),
        "Producing Wells (PDP)": (count("Well"), "PDP laterals mapped to wells", {"file": "LSB_PDP_20260904.shp", "locator": "all features"}),
    }
    if wi:
        metrics["Avg Working Interest"] = (mean(wi) * 100, "mean ComboCurve WI Oil (%) over 640 locations", {**oneline, "locator": "ONELINE!JP2:JP641"})
    if nri:
        metrics["Avg Net Revenue Interest"] = (mean(nri) * 100, "mean ComboCurve NRI Oil (%) over 640 locations", {**oneline, "locator": "ONELINE!JQ2:JQ641"})
    if locations:
        metrics["Operated %"] = (operated / len(locations) * 100, "share of locations operated by LONE STAR BASIN OPERATING LLC", {**oneline, "locator": "ONELINE!M2:M641"})
    return metrics
