"""Named operations: the only way the chatbot reads data. Each returns a result, citations and UI actions."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..config import slug
from ..ontology.build import ZONES
from ..ontology.store import Snapshot

BENCH_NAMES = {"WCA": "Wolfcamp A", "WCB I": "Wolfcamp B1", "WCB II": "Wolfcamp B2", "WCC": "Wolfcamp C", "WCD": "Wolfcamp D", "MSS": "Middle Spraberry Shale", "LSS": "Lower Spraberry Shale", "USS": "Upper Spraberry Shale", "JM": "Jo Mill"}
OPERATIONS = {
    "room_overview": "Counts of files, entities, links, facts and open issues in the snapshot.",
    "zone_summary": "Net acres, net locations (10K equivalents) and economic locations with both 10% value columns for one bench (zone code such as WCA).",
    "unit_profile": "One unit: county, development area, acreage, assigned locations, laterals, tracts, ownership conflicts.",
    "well_profile": "One well or economic location (by API, well name or INPT ID): status, zone, both unit assignments, economics, issues.",
    "locations": "Economic locations filtered by zone, status and/or unit, with value totals.",
    "conflicts": "Open issues by rule (or for one entity), with severity and what each blocks.",
    "claim_check": "Document headline claims compared with values computed from the room.",
    "gap_report": "Missing links and unmapped data: crosswalk, zone aliases, unmatched keys, uncached formulas.",
    "lineage": "Sources for an entity: file, sheet and cell, map feature or page, for the entity, its links and facts.",
}


def result(operation: str, args: dict[str, Any], data: dict[str, Any], summary: str, citations: list[dict[str, Any]], actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"operation": operation, "args": args, "data": data, "summary": summary, "citations": citations[:8], "actions": actions or []}


def cite(file: str | None, locator: str | None, label: str | None = None) -> dict[str, Any]:
    return {"file": file, "locator": locator, "label": label or f"{(file or '').split('/')[-1]} {locator or ''}".strip()}


def resolve_entity(snap: Snapshot, query: str, types: set[str] | None = None) -> dict[str, Any] | None:
    text = query.strip()
    if text in snap.nodes:
        return snap.nodes[text]
    digits = re.sub(r"\D", "", text)
    if len(digits) in (10, 12, 14):
        api = digits.ljust(14, "0")
        if f"well:{api}" in snap.nodes:
            return snap.nodes[f"well:{api}"]
    lowered = text.lower()
    best, score = None, 0
    for node in snap.nodes.values():
        if types and node["type"] not in types:
            continue
        label = node["label"].lower()
        candidates = [label, node["key"].lower(), *(alias.lower() for alias in snap.aliases.get(node["id"], []))]
        if lowered in candidates:
            current = 100
        elif any(c.startswith(lowered) for c in candidates):
            current = 60
        elif any(lowered in c for c in candidates):
            current = 30
        else:
            continue
        if current > score:
            best, score = node, current
    return best


def zone_code(text: str) -> str | None:
    upper = text.strip().upper()
    if upper in ZONES:
        return upper
    for code, name in BENCH_NAMES.items():
        if name.upper() == upper or name.upper().replace(" ", "") == upper.replace(" ", ""):
            return code
    return None


def room_overview(snap: Snapshot) -> dict[str, Any]:
    counts = snap.meta["counts"]
    open_issues = [i for i in snap.issues if i["status"] == "open"]
    data = {
        "snapshot_id": snap.snapshot_id,
        "status": snap.meta["status"],
        "files": len(snap.manifest["files"]),
        "entities_by_type": counts["entities_by_type"],
        "relationships": counts["relationships"],
        "facts": counts["facts"],
        "open_issues": len(open_issues),
        "open_blocking": sum(i["severity"] == "blocking" for i in open_issues),
    }
    summary = f"{data['files']} files produced {counts['entities']:,} entities, {counts['relationships']:,} links and {counts['facts']:,} facts; {data['open_issues']:,} issues are open ({data['open_blocking']:,} blocking)."
    return result("room_overview", {}, data, summary, [cite(f["path"], "file") for f in snap.manifest["files"] if f["kind"] in {"excel", "pdf", "gis_layer"}][:6], [{"type": "view", "view": "explore", "mode": "schema", "label": "Show schema graph"}])


def zone_summary(snap: Snapshot, zone: str) -> dict[str, Any]:
    code = zone_code(zone) or zone.upper()
    acres = snap.sql("select sum(value) from facts where measure = 'net_acres' and zone = ?", [code])[0][0] or 0
    net_locations = snap.sql(
        "select sum(l.value * w.value) from facts l join facts w using (subject, zone) where zone = ? and l.measure = 'gross_locations_10k' and w.measure = 'operational_wi'", [code]
    )[0][0] or 0
    zone_id = f"zone:{slug(code)}"
    locations = [e["source"] for e in snap.inn.get(zone_id, []) if e["kind"] == "TARGETS_ZONE"]
    by_status: dict[str, dict[str, float]] = {}
    for location in locations:
        node = snap.nodes[location]
        status = node["props"].get("status", "UNKNOWN")
        row = by_status.setdefault(status, {"count": 0, "ky_musd": 0.0, "mf_musd": 0.0})
        row["count"] += 1
    if locations:
        for subject, measure, value in snap.sql(
            f"select subject, measure, value from facts where measure in ('dcf10_ky', 'dcf10_mf') and subject in ({','.join('?' * len(locations))})", locations
        ):
            key = "ky_musd" if measure == "dcf10_ky" else "mf_musd"
            by_status[snap.nodes[subject]["props"].get("status", "UNKNOWN")][key] += value / 1000
    table = [{"status": status, **{k: round(v, 1) if isinstance(v, float) else v for k, v in row.items()}} for status, row in sorted(by_status.items(), key=lambda item: -item[1]["count"])]
    pv_conflicts = sum(1 for location in locations for issue in snap.issues_by_subject.get(location, []) if issue["rule"] == "VALUE_FIELD_CONFLICT" and issue["status"] == "open")
    index = ZONES.index(code) if code in ZONES else 0
    column = lambda start: _col(start, index)  # noqa: E731
    data = {"zone": code, "zone_name": BENCH_NAMES.get(code, code), "net_acres": round(acres, 2), "net_locations_10k": round(net_locations, 2), "economic_locations": len(locations), "by_status": table, "pv10_open_conflicts": pv_conflicts}
    summary = (
        f"{data['zone_name']} ({code}): {acres:,.2f} net acres and {net_locations:,.2f} net locations (10,000-ft equivalents x operational WI) from Unit Details; "
        f"{len(locations)} economic locations target this bench."
        + (f" PV-10 is not resolved: both '10% Discount Cash Flow' columns are shown because {pv_conflicts} locations have an open VALUE_FIELD_CONFLICT." if pv_conflicts else "")
    )
    unit_details = "Lone Star Basin Unit Details_vF_2026.08.06.xlsx"
    oneline = "Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx"
    citations = [
        cite(unit_details, f"Unit Details!{column('K')}8:{column('K')}97", f"Unit Details {column('K')}8:{column('K')}97 net acres"),
        cite(unit_details, f"Unit Details!{column('CM')}8:{column('CM')}97", f"Unit Details {column('CM')}8:{column('CM')}97 WI"),
        cite(unit_details, f"Unit Details!{column('DS')}8:{column('DS')}97", f"Unit Details {column('DS')}8:{column('DS')}97 locations"),
        cite(oneline, "ONELINE!KY2:KY641", "ONELINE KY (10% DCF)"),
        cite(oneline, "ONELINE!MF2:MF641", "ONELINE MF (10% DCF, same header)"),
    ]
    actions = [{"type": "focus", "entity": zone_id, "label": "Show on graph"}]
    if pv_conflicts:
        actions.append({"type": "review", "rule": "VALUE_FIELD_CONFLICT", "label": "Review PV-10 conflict"})
    return result("zone_summary", {"zone": code}, data, summary, citations, actions)


def _col(start: str, offset: int) -> str:
    index = sum((ord(c) - 64) * 26**i for i, c in enumerate(reversed(start))) + offset
    text = ""
    while index:
        index, rem = divmod(index - 1, 26)
        text = chr(65 + rem) + text
    return text


def unit_profile(snap: Snapshot, unit: str) -> dict[str, Any]:
    node = resolve_entity(snap, unit, {"Unit"})
    if not node:
        return result("unit_profile", {"unit": unit}, {"found": False}, f"No unit matches '{unit}'.", [])
    uid = node["id"]
    link = lambda kind, direction="in": [e for e in (snap.inn if direction == "in" else snap.out).get(uid, []) if e["kind"] == kind]  # noqa: E731
    county = next((snap.nodes[e["target"]]["label"] for e in link("IN_COUNTY", "out")), None)
    devarea = next((snap.nodes[e["target"]]["label"] for e in link("IN_DEV_AREA", "out")), None)
    issues = snap.issues_by_subject.get(uid, [])
    ownership = [i for i in issues if i["rule"] == "OWNERSHIP_VALUE_CONFLICT"]
    wi = {f["zone"]: f["value"] for f in snap.facts(uid, "operational_wi")}
    gis = {f["zone"]: f["value"] for f in snap.facts(uid, "gis_wi")}
    data = {
        "unit": node["label"], "id": uid, "county": county, "development_area": devarea,
        "gross_acres": node["props"].get("gross_acres"), "mapped_acres": round(node["props"].get("mapped_acres") or 0, 2),
        "assigned_locations": len(link("ASSIGNED_TO_UNIT")), "laterals_inside": len(link("LATERAL_IN_UNIT")), "tracts_inside": len(link("WITHIN_UNIT")),
        "ownership_conflicts": len(ownership),
        "wi_by_zone": [{"zone": z, "workbook": round(wi.get(z, 0), 4), "gis": round(gis.get(z, 0), 4)} for z in ZONES],
        "aliases": snap.aliases.get(uid, []),
    }
    summary = (
        f"{node['label']} ({county} County, {devarea}): {data['gross_acres']:,.2f} contractual gross acres ({data['mapped_acres']:,.0f} mapped). "
        f"ComboCurve assigns {data['assigned_locations']} locations to it; {data['laterals_inside']} PDP laterals and {data['tracts_inside']} leasehold tracts lie inside it on the map. "
        + (f"GIS working interest disagrees with Unit Details in {len(ownership)} of 15 zones." if ownership else "GIS and workbook ownership agree.")
    )
    return result("unit_profile", {"unit": node["label"]}, data, summary, [cite(node["file"], node["locator"])], [{"type": "inspect", "entity": uid, "label": "Details"}, {"type": "focus", "entity": uid, "label": "Show on graph"}])


def well_profile(snap: Snapshot, well: str) -> dict[str, Any]:
    node = resolve_entity(snap, well, {"Well", "EconomicLocation"})
    if not node:
        return result("well_profile", {"well": well}, {"found": False}, f"No well or location matches '{well}'.", [])
    if node["type"] == "Well":
        well_node = node
        location = next((snap.nodes[e["source"]] for e in snap.inn.get(node["id"], []) if e["kind"] == "IS_WELL"), None)
    else:
        location = node
        well_node = next((snap.nodes[e["target"]] for e in snap.out.get(node["id"], []) if e["kind"] == "IS_WELL"), None)
    assigned = next((e for e in snap.out.get(location["id"], []) if e["kind"] == "ASSIGNED_TO_UNIT"), None) if location else None
    spatial = next((e for e in snap.out.get(well_node["id"], []) if e["kind"] == "LATERAL_IN_UNIT"), None) if well_node else None
    economics = {f["measure"]: f for f in snap.facts(location["id"])} if location else {}
    production_facts = [f for f in snap.facts(well_node["id"]) if f["measure"] in {"oil_bbl", "gas_mcf", "water_bbl", "days_on"}] if well_node else []
    latest_oil = max((f for f in production_facts if f["measure"] == "oil_bbl"), key=lambda f: f["period"] or "", default=None)
    production: dict[str, dict[str, Any]] = {}
    for fact in sorted(production_facts, key=lambda f: f["period"] or ""):
        production.setdefault(fact["period"], {"month": fact["period"]})[fact["measure"]] = fact["value"]
    issues = [*(snap.issues_by_subject.get(well_node["id"], []) if well_node else []), *(snap.issues_by_subject.get(location["id"], []) if location else [])]
    props = (location or well_node)["props"]
    data = {
        "well": (well_node or location)["label"],
        "api_14": well_node["props"].get("api_14") if well_node else None,
        "location_id": location["id"] if location else None,
        "status": props.get("status"),
        "landing_zone": props.get("landing_zone"),
        "unit_comboCurve": snap.nodes[assigned["target"]]["label"] if assigned else None,
        "unit_map": snap.nodes[spatial["target"]]["label"] if spatial else None,
        "wi": economics.get("wi", {}).get("value"),
        "nri": economics.get("nri", {}).get("value"),
        "irr": economics.get("irr", {}).get("value"),
        "dcf10_ky_musd": round(economics["dcf10_ky"]["value"] / 1000, 3) if "dcf10_ky" in economics else None,
        "dcf10_mf_musd": round(economics["dcf10_mf"]["value"] / 1000, 3) if "dcf10_mf" in economics else None,
        "issues": [{"rule": i["rule"], "severity": i["severity"], "detail": i["detail"], "status": i["status"]} for i in issues],
        "monthly_production": list(production.values()),
    }
    parts = [f"{data['well']}: {str(data['status'] or 'mapped well').lower()}" + (f", {data['landing_zone']}" if data["landing_zone"] else "")]
    if data["wi"] is not None:
        parts.append(f"WI {data['wi']:.1%}, NRI {data['nri']:.1%}" + (f", IRR {data['irr']:.1%}" if data["irr"] is not None else ""))
    if data["unit_comboCurve"] and data["unit_map"] and data["unit_comboCurve"] != data["unit_map"]:
        parts.append(f"two unit assignments are kept: ComboCurve says {data['unit_comboCurve']}, but the lateral lies in {data['unit_map']}")
    elif data["unit_comboCurve"]:
        parts.append(f"unit {data['unit_comboCurve']}")
    if data["dcf10_ky_musd"] is not None:
        parts.append(f"10% discount cash flow ${data['dcf10_ky_musd']:.2f} MM (KY) vs ${data['dcf10_mf_musd']:.2f} MM (MF)")
    if production:
        months = list(production.values())
        latest = months[-1]
        parts.append(
            f"monthly production from an approved seller dataset covers {months[0]['month'][:7]} to {latest['month'][:7]}; "
            f"{latest['month'][:7]}: {latest.get('oil_bbl', 0):,.0f} bbl oil, {latest.get('gas_mcf', 0):,.0f} mcf gas, {latest.get('water_bbl', 0):,.0f} bbl water"
        )
    citations = [c for c in [
        cite(location["file"], location["locator"]) if location else None,
        cite(assigned["file"], assigned["locator"], f"ComboCurve UNIT {assigned['locator']}") if assigned else None,
        cite(well_node["file"], well_node["locator"], f"PDP {well_node['locator']}") if well_node else None,
        cite(economics["dcf10_ky"]["file"], economics["dcf10_ky"]["locator"]) if "dcf10_ky" in economics else None,
        cite(economics["dcf10_mf"]["file"], economics["dcf10_mf"]["locator"]) if "dcf10_mf" in economics else None,
        cite(latest_oil["file"], latest_oil["locator"], f"seller production oil {latest_oil['locator']}") if latest_oil else None,
    ] if c]
    target = (well_node or location)["id"]
    return result("well_profile", {"well": data["well"]}, data, "; ".join(parts) + ".", citations, [{"type": "inspect", "entity": target, "label": "Details"}, {"type": "focus", "entity": target, "label": "Show on graph"}])


def locations(snap: Snapshot, zone: str | None = None, status: str | None = None, unit: str | None = None) -> dict[str, Any]:
    code = zone_code(zone) if zone else None
    unit_node = resolve_entity(snap, unit, {"Unit"}) if unit else None
    selected = []
    for node in snap.nodes.values():
        if node["type"] != "EconomicLocation":
            continue
        if status and str(node["props"].get("status", "")).upper() != status.upper():
            continue
        if code and not any(e["kind"] == "TARGETS_ZONE" and e["target"] == f"zone:{slug(code)}" for e in snap.out.get(node["id"], [])):
            continue
        if unit_node and not any(e["kind"] == "ASSIGNED_TO_UNIT" and e["target"] == unit_node["id"] for e in snap.out.get(node["id"], [])):
            continue
        selected.append(node)
    ids = [n["id"] for n in selected]
    totals = {"dcf10_ky_musd": 0.0, "dcf10_mf_musd": 0.0}
    if ids:
        for measure, total in snap.sql(f"select measure, sum(value) from facts where measure in ('dcf10_ky', 'dcf10_mf') and subject in ({','.join('?' * len(ids))}) group by 1", ids):
            totals[f"{measure}_musd"] = round(total / 1000, 1)
    data = {"count": len(selected), "by_status": dict(Counter(n["props"].get("status") for n in selected)), **totals, "sample": [{"id": n["id"], "label": n["label"], "status": n["props"].get("status")} for n in selected[:12]]}
    filters = ", ".join(f"{k} {v}" for k, v in (("zone", code), ("status", status), ("unit", unit_node["label"] if unit_node else None)) if v) or "all"
    summary = f"{len(selected)} economic locations ({filters}); 10% discount cash flow totals ${totals['dcf10_ky_musd']:,.1f} MM (KY) vs ${totals['dcf10_mf_musd']:,.1f} MM (MF)."
    return result("locations", {"zone": code, "status": status, "unit": unit_node["label"] if unit_node else None}, data, summary, [cite("Lone Star Basin ComboCurve Oneline and Project Link_2026.08.07.xlsx", "ONELINE")])


def conflicts(snap: Snapshot, rule: str | None = None, entity: str | None = None) -> dict[str, Any]:
    node = resolve_entity(snap, entity) if entity else None
    issues = snap.issues_by_subject.get(node["id"], []) if node else snap.issues
    if rule:
        issues = [i for i in issues if i["rule"] == rule.upper()]
    by_rule: dict[str, dict[str, Any]] = {}
    for issue in issues:
        row = by_rule.setdefault(issue["rule"], {"rule": issue["rule"], "severity": issue["severity"], "blocks": issue["blocks"], "open": 0, "decided": 0})
        row["open" if issue["status"] == "open" else "decided"] += 1
    rows = sorted(by_rule.values(), key=lambda r: ({"blocking": 0, "warning": 1, "info": 2}[r["severity"]], -r["open"]))
    data = {"rules": rows, "examples": [{"issue_id": i["issue_id"], "subject": i["subject"], "detail": i["detail"]} for i in issues[:5]]}
    scope = f" for {node['label']}" if node else ""
    blocking = [r for r in rows if r["severity"] == "blocking" and r["open"]]
    summary = f"{sum(r['open'] for r in rows):,} open issues{scope} across {len(rows)} rules." + (" Blocking: " + "; ".join(f"{r['rule']} ({r['open']:,}) blocks {r['blocks']}" for r in blocking) + "." if blocking else "")
    citations = [cite(a.get("file"), a.get("locator")) for i in issues[:3] for a in i["assertions"] if a.get("file")]
    return result("conflicts", {"rule": rule, "entity": node["label"] if node else None}, data, summary, citations, [{"type": "review", "rule": rows[0]["rule"] if rows else None, "label": "Open review queue"}])


def claim_check(snap: Snapshot, document: str | None = None) -> dict[str, Any]:
    claims = [n for n in snap.nodes.values() if n["type"] == "DocumentClaim" and (not document or document.lower() in (n["file"] or "").lower() or document.lower() in n["props"].get("file_id", ""))]
    rows = [{"claim": n["props"]["raw"], "page": n["props"]["page"], "file": n["file"], "check": n["props"].get("check"), "computed": n["props"].get("computed"), "computed_from": n["props"].get("computed_from")} for n in claims]
    counts = Counter(r["check"] for r in rows)
    figures = []
    for doc in snap.documents.values():
        for figure in doc["figures"]:
            chart = figure.get("chart") or {}
            if "ownership" in (chart.get("title") or "").lower():
                wi = next((s for s in chart["series"] if s["name"].lower().startswith("working")), None)
                book: dict[str, float] = {}
                for zone, value in snap.sql("select zone, avg(value) * 100 from facts where measure = 'operational_wi' group by 1"):
                    book[zone] = value
                if wi:
                    figures.append({"file": doc["file"], "figure": figure["id"], "page": figure["page"], "rows": [{"zone": z, "chart": p["y"], "read_as": p["x"], "workbook": round(book.get(z, 0), 1), "delta": round(p["y"] - book.get(z, 0), 1) if p["y"] is not None else None} for z, p in zip(ZONES, wi["points"])]})
    data = {"claims": rows, "counts": dict(counts), "chart_checks": figures}
    mismatches = [r for r in rows if r["check"] == "mismatch"]
    summary = f"{len(rows)} headline claims: {counts.get('match', 0)} match the room, {counts.get('mismatch', 0)} do not, {counts.get('unverifiable', 0)} cannot be computed from the room." + (" Mismatches: " + "; ".join(f"{r['claim']} (page {r['page']}) vs {r['computed']:,.2f} computed from {r['computed_from']}" for r in mismatches) + "." if mismatches else "")
    if figures:
        within = sum(1 for r in figures[0]["rows"] if r["delta"] is not None and abs(r["delta"]) <= 0.5)
        summary += f" The ownership chart (page {figures[0]['page']}) matches Unit Details within 0.5 points for {within} of 15 zones; chart values are approximate."
    citations = [cite(r["file"], f"page {r['page']}", f"{r['file'].split('/')[-1]} p.{r['page']}") for r in mismatches] + [cite(f["file"], f"page {f['page']}", f"figure {f['figure']} p.{f['page']}") for f in figures]
    return result("claim_check", {"document": document}, data, summary, citations, [{"type": "document", "file_id": "asset-overview", "page": figures[0]["page"] if figures else 2, "label": "Open document"}])


def gap_report(snap: Snapshot) -> dict[str, Any]:
    counts = Counter(i["rule"] for i in snap.issues if i["status"] == "open")
    batteries = sum(n["type"] == "BatteryCode" for n in snap.nodes.values())
    facilities = sum(n["type"] == "PricingFacility" for n in snap.nodes.values())
    data = {
        "pricing_crosswalk": {"battery_codes": batteries, "pricing_facilities": facilities, "linked": 0},
        "unmapped_landing_zones": counts.get("ZONE_ALIAS_MISSING", 0),
        "uncached_formula_groups": counts.get("FORMULA_CACHE_MISSING", 0),
        "unmatched_keys": counts.get("UNMATCHED_KEY", 0),
        "unverifiable_claims": sum(1 for n in snap.nodes.values() if n["type"] == "DocumentClaim" and n["props"].get("check") == "unverifiable"),
        "proposed_mappings": sum(1 for m in snap.mappings if m["status"] == "proposed"),
    }
    summary = (
        f"Gaps: no crosswalk links {batteries} battery codes to {facilities} basis-report facilities, so price answers are unsupported; "
        f"{data['unmapped_landing_zones']} locations have a landing zone with no approved bench; {data['uncached_formula_groups']} LOS line items contain formulas without saved values; "
        f"{data['unverifiable_claims']} document claims cannot be computed from the room"
        + (f"; {data['proposed_mappings']} field mappings await approval" if data["proposed_mappings"] else "")
        + (f"; {data['unmatched_keys']} datasets have unmatched keys" if data["unmatched_keys"] else "") + "."
    )
    return result("gap_report", {}, data, summary, [], [{"type": "review", "rule": "CROSSWALK_MISSING", "label": "Open gaps in review"}])


def lineage(snap: Snapshot, entity: str) -> dict[str, Any]:
    node = resolve_entity(snap, entity)
    if not node:
        return result("lineage", {"entity": entity}, {"found": False}, f"No entity matches '{entity}'.", [])
    links = [*snap.out.get(node["id"], []), *snap.inn.get(node["id"], [])]
    facts = snap.facts(node["id"])
    files = Counter([node["file"], *(e["file"] for e in links), *(f["file"] for f in facts)])
    data = {"entity": node["label"], "id": node["id"], "type": node["type"], "files": [{"file": f, "uses": n} for f, n in files.most_common() if f], "links": len(links), "facts": len(facts), "aliases": snap.aliases.get(node["id"], [])}
    summary = f"{node['label']} ({node['type']}) is built from {len([f for f in files if f])} files: " + "; ".join(f"{f.split('/')[-1]} ({n})" for f, n in files.most_common() if f) + "."
    citations = [cite(node["file"], node["locator"]), *(cite(e["file"], e["locator"], f"{e['kind']} {e['locator']}") for e in links[:4])]
    return result("lineage", {"entity": node["label"]}, data, summary, citations, [{"type": "inspect", "entity": node["id"], "label": "Details"}])


def run_operation(snap: Snapshot, name: str, args: dict[str, Any]) -> dict[str, Any]:
    functions = {
        "room_overview": room_overview, "zone_summary": zone_summary, "unit_profile": unit_profile, "well_profile": well_profile,
        "locations": locations, "conflicts": conflicts, "claim_check": claim_check, "gap_report": gap_report, "lineage": lineage,
    }
    if name not in functions:
        raise ValueError(f"unknown operation {name}")
    return functions[name](snap, **{k: v for k, v in args.items() if v not in (None, "")})
