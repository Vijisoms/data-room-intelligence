"""Build Gold ontology tables (entities, links, facts, geometry) from a Silver snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from ..config import slug
from ..contracts import AliasTable, Catalog
from ..parsers import _api_number

ZONES = ["USS", "MSS", "JM", "LSS", "DEAN", "WCA", "WCB I", "WCB II", "WCC", "WCD", "STR / BND", "UP BRNT", "LR BRNT", "MSSP", "WDFD"]
UNIT_BLOCKS = {"K": "net_acres", "AA": "total_nri", "AQ": "base_nri", "BG": "orri", "BW": "nri_8_8ths", "CM": "operational_wi", "DC": "net_acres_with_carry", "DS": "gross_locations_10k"}
ONELINE_MEASURES = {
    "WI Oil (%)": ("wi", "fraction", 1.0),
    "NRI Oil (%)": ("nri", "fraction", 1.0),
    "10% Discount Cash Flow (M$)": ("dcf10_ky", "M$", 1.0),
    "10% Discount Cash Flow (M$).1": ("dcf10_mf", "M$", 1.0),
    "IRR (%)": ("irr", "fraction", 0.01),
    "Net Oil Sales Volume (MBBL)": ("net_oil_mbbl", "MBBL", 1.0),
    "Net Gas Sales Volume (MMCF)": ("net_gas_mmcf", "MMCF", 1.0),
    "Net BOE Sales Volume (MBBL)": ("net_boe_mbbl", "MBOE", 1.0),
    "Total Net Revenue (M$)": ("net_revenue", "M$", 1.0),
    "Perf Lateral Length (FT)": ("perf_lateral_ft", "ft", 1.0),
}
SELLER_OPERATOR = "LONE STAR BASIN OPERATING LLC"


def col_index(letters: str) -> int:
    return sum((ord(c) - 64) * 26**i for i, c in enumerate(reversed(letters)))


def col_letter(index: int) -> str:
    text = ""
    while index:
        index, rem = divmod(index - 1, 26)
        text = chr(65 + rem) + text
    return text


def norm_name(value: Any) -> str:
    return " ".join(str(value).upper().replace("_", " ").split())


@dataclass
class Gold:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    geometries: list[dict[str, Any]] = field(default_factory=list)
    aliases: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    def node(self, type_: str, prefix: str, key: Any, display: Any, file: str | None, locator: str | None, **props: Any) -> str:
        node_id = f"{prefix}:{key}"
        if node_id not in self.nodes:
            self.nodes[node_id] = {"id": node_id, "type": type_, "key": str(key), "label": str(display), "file": file, "locator": locator, "props": {}}
        self.nodes[node_id]["props"].update({k: v for k, v in props.items() if v is not None})
        return node_id

    def edge(self, source: str, kind: str, target: str, method: str, file: str | None, locator: str | None, **props: Any) -> None:
        self.edges.append({"id": f"{kind}:{source}->{target}", "source": source, "kind": kind, "target": target, "method": method, "file": file, "locator": locator, "props": props})

    def fact(self, subject: str, measure: str, value: float | None, unit: str, file: str, locator: str, quality: str = "ok", **dims: Any) -> None:
        self.facts.append(
            {
                "subject": subject,
                "measure": measure,
                "value": value,
                "unit": unit,
                "zone": dims.get("zone"),
                "period": dims.get("period"),
                "item": dims.get("item"),
                "section": dims.get("section"),
                "case_id": dims.get("case_id"),
                "dataset_id": dims.get("dataset_id"),
                "file": file,
                "locator": locator,
                "quality": quality,
            }
        )

    def alias(self, entity: str, alias: str, source: str) -> None:
        if alias and alias != self.nodes[entity]["label"]:
            self.aliases.append({"entity": entity, "alias": alias, "source": source})


class Silver:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.tables = {t["dataset_id"]: t for t in json.loads((path / "tabular" / "tables.json").read_text("utf-8"))}
        values = path / "tabular" / "values.parquet"
        self.con = duckdb.connect()
        if values.exists():
            self.con.execute(f"create view v as select * from read_parquet('{values.as_posix()}')")
        self.documents = [json.loads(p.read_text("utf-8")) for p in sorted((path / "documents").glob("*/document.json"))]
        self.manifest = json.loads((path.parent / "bronze" / "manifest.json").read_text("utf-8"))

    def file_of(self, file_id: str) -> str | None:
        return next((f["path"] for f in self.manifest["files"] if f["file_id"] == file_id), None)

    def records(self, dataset_id: str) -> list[tuple[int, dict[str, Any], dict[str, str]]]:
        rows: dict[int, tuple[dict[str, Any], dict[str, str]]] = {}
        for row, column, num, text, quality in self.con.execute(
            'select "row", "column", num, text, quality from v where dataset_id = ? order by "row"', [dataset_id]
        ).fetchall():
            values, qualities = rows.setdefault(row, ({}, {}))
            values[column] = num if num is not None else text
            qualities[column] = quality
        return [(row, values, qualities) for row, (values, qualities) in sorted(rows.items())]

    def column_by_header(self, dataset_id: str) -> dict[str, str]:
        return {" > ".join(path): column for column, path in self.tables[dataset_id]["headers"].items()}

    def geo(self, file_id: str) -> dict[str, Any]:
        return json.loads((self.path / "gis" / f"{file_id}.geojson").read_text("utf-8"))

    def features(self) -> list[dict[str, Any]]:
        path = self.path / "gis" / "features.parquet"
        return duckdb.sql(f"select * from read_parquet('{path.as_posix()}')").to_df().to_dict("records") if path.exists() else []

    def candidates(self) -> list[dict[str, Any]]:
        path = self.path / "gis" / "spatial_candidates.parquet"
        return duckdb.sql(f"select * from read_parquet('{path.as_posix()}')").to_df().to_dict("records") if path.exists() else []


def build(silver_path: Path, catalog: Catalog, aliases: dict[str, AliasTable], room_name: str = "Lone Star Basin") -> Gold:
    silver = Silver(silver_path)
    gold = Gold()
    prefixes = {item.name: item.id_prefix for item in catalog.entity_types}
    p = lambda name: prefixes[name]  # noqa: E731
    asset = gold.node("Asset", p("Asset"), slug(room_name), room_name, None, "room inventory", name=room_name)
    gold.context.update({"asset": asset, "prefixes": prefixes})
    zone_ids = {zone: gold.node("Zone", p("Zone"), slug(zone), zone, None, "Unit Details zone headers", code=zone) for zone in ZONES}
    units = _unit_details(silver, gold, p, zone_ids, asset)
    _gis(silver, gold, p, units, zone_ids, aliases["gis_zone_fields"])
    _economics(silver, gold, p, units, zone_ids, aliases["landing_zones"])
    _cashflow(silver, gold, p, asset)
    _los(silver, gold, p, asset)
    _basis(silver, gold, p, asset)
    _documents(silver, gold, p, asset)
    return gold


def _unit_details(silver: Silver, gold: Gold, p, zone_ids: dict[str, str], asset: str) -> dict[str, str]:
    dataset = next(d for d, t in silver.tables.items() if t["family"] == "unit_details")
    file = silver.tables[dataset]["file"]
    units: dict[str, str] = {}
    for row, values, _ in silver.records(dataset):
        name = values.get("C")
        if not name:
            continue
        unit = gold.node("Unit", p("Unit"), slug(name), name, file, f"Unit Details!C{row}", name=name, gross_acres=values.get("H"), lateral_length_ft=values.get("I"))
        units[norm_name(name)] = unit
        county = gold.node("County", p("County"), slug(values["D"]), values["D"], file, f"Unit Details!D{row}", name=values["D"])
        devarea = gold.node("DevelopmentArea", p("DevelopmentArea"), slug(values["F"]), values["F"], file, f"Unit Details!F{row}", name=values["F"])
        gold.edge(unit, "IN_COUNTY", county, "source", file, f"Unit Details!D{row}")
        gold.edge(unit, "IN_DEV_AREA", devarea, "source", file, f"Unit Details!F{row}")
        gold.edge(unit, "PART_OF", asset, "source", file, f"Unit Details!C{row}")
        for start, measure in UNIT_BLOCKS.items():
            unit_name = "acres" if "acres" in measure else "wells" if "locations" in measure else "fraction"
            for index, zone in enumerate(ZONES):
                column = col_letter(col_index(start) + index)
                value = values.get(column)
                gold.fact(unit, measure, float(value) if isinstance(value, (int, float)) else None, unit_name, file, f"Unit Details!{column}{row}", zone=zone, dataset_id=dataset)
    return units


def _gis(silver: Silver, gold: Gold, p, units: dict[str, str], zone_ids: dict[str, str], zone_fields: AliasTable) -> None:
    features = silver.features()
    by_dataset: dict[str, list[dict[str, Any]]] = {}
    for item in features:
        by_dataset.setdefault(item["dataset_id"].split("/")[0], []).append(item)
    file = {fid: silver.file_of(fid) for fid in by_dataset}
    unit_by_index: dict[int, str] = {}
    for item in by_dataset.get("gis-units-pf", []):
        attrs = json.loads(item["attributes"])
        unit = units.get(norm_name(attrs["UNIT_NAME"]))
        if unit is None:
            continue
        unit_by_index[item["feature_index"]] = unit
        gold.alias(unit, attrs["UNIT_NAME"], f"{file['gis-units-pf']} UNIT_NAME")
        gold.nodes[unit]["props"]["mapped_acres"] = item["geodesic_acres"]
        gold.geometries.append({"entity": unit, "kind": "polygon", "wkb": item["wkb"], "geodesic_acres": item["geodesic_acres"], "length_ft": None, "file": file["gis-units-pf"], "locator": f"feature {item['feature_index']}"})
    for item in by_dataset.get("gis-units", []):
        attrs = json.loads(item["attributes"])
        unit = units.get(norm_name(attrs["UNIT"]))
        if unit is None:
            continue
        for name, value in attrs.items():
            prefix, _, suffix = name.partition("_")
            zone = zone_fields.entries.get(suffix)
            if prefix in {"WI", "NRI"} and zone:
                gold.fact(unit, f"gis_{prefix.lower()}", float(value), "fraction", file["gis-units"], f"feature {item['feature_index']} {name}", zone=zone, dataset_id=item["dataset_id"])
    tract_by_index: dict[int, str] = {}
    for item in by_dataset.get("gis-leasehold", []):
        attrs = json.loads(item["attributes"])
        key = hashlib.sha256(item["wkb"]).hexdigest()[:12]
        tract = gold.node("LeaseholdTract", p("LeaseholdTract"), key, f"Tract {item['feature_index']}", file["gis-leasehold"], f"feature {item['feature_index']}", geometry_hash=key, status=attrs.get("STATUS"), mapped_acres=item["geodesic_acres"])
        tract_by_index[item["feature_index"]] = tract
        gold.geometries.append({"entity": tract, "kind": "polygon", "wkb": item["wkb"], "geodesic_acres": item["geodesic_acres"], "length_ft": None, "file": file["gis-leasehold"], "locator": f"feature {item['feature_index']}"})
    well_by_index: dict[int, str] = {}
    for item in by_dataset.get("gis-pdp", []):
        attrs = json.loads(item["attributes"])
        api = _api_number(attrs["API_14"], 14)
        well = gold.node("Well", p("Well"), api, attrs.get("Well_Name") or api, file["gis-pdp"], f"feature {item['feature_index']}", api_14=api, api_10=_api_number(attrs.get("API_10"), 10), well_name=attrs.get("Well_Name"), landing_zone=attrs.get("Landing_Zo"), lateral_length_ft=item["geodesic_length_ft"])
        well_by_index[item["feature_index"]] = well
        gold.alias(well, gold.nodes[well]["props"].get("api_10"), "API_10")
        gold.geometries.append({"entity": well, "kind": "line", "wkb": item["wkb"], "geodesic_acres": None, "length_ft": item["geodesic_length_ft"], "file": file["gis-pdp"], "locator": f"feature {item['feature_index']}"})
    for link in silver.candidates():
        index, target = link["source_index"], link["target_index"]
        if link["kind"] == "lateral_in_unit" and index in well_by_index and target in unit_by_index:
            gold.edge(well_by_index[index], "LATERAL_IN_UNIT", unit_by_index[target], "spatial", file["gis-pdp"], f"feature {index} covered by unit feature {target}")
        elif link["kind"] == "lateral_crosses_tract" and index in well_by_index and target in tract_by_index:
            gold.edge(well_by_index[index], "CROSSES_TRACT", tract_by_index[target], "spatial", file["gis-pdp"], f"feature {index} intersects leasehold feature {target}", length_ft=link["measure"])
        elif link["kind"] == "tract_within_unit" and index in tract_by_index and target in unit_by_index:
            gold.edge(tract_by_index[index], "WITHIN_UNIT", unit_by_index[target], "spatial", file["gis-leasehold"], f"feature {index} covered by unit feature {target}")
    gold.context["wells_by_api"] = {gold.nodes[w]["props"]["api_14"]: w for w in well_by_index.values()}


def _economics(silver: Silver, gold: Gold, p, units: dict[str, str], zone_ids: dict[str, str], landing: AliasTable) -> None:
    dataset = "combocurve/oneline"
    if dataset not in silver.tables:
        return
    file = silver.tables[dataset]["file"]
    cols = silver.column_by_header(dataset)
    wells = gold.context.get("wells_by_api", {})
    case = None
    for row, values, _ in silver.records(dataset):
        get = lambda header: values.get(cols.get(header, "?"))  # noqa: E731
        if case is None:
            case = gold.node("EconomicCase", p("EconomicCase"), slug(get("Project Name")), get("Project Name"), file, f"ONELINE!{cols['Project Name']}{row}", project=get("Project Name"), scenario=get("Scenario Name"), pricing=get("Pricing Qualifier"), as_of=get("As Of Date"))
        inpt = get("INPT ID")
        location = gold.node(
            "EconomicLocation", p("EconomicLocation"), inpt, get("Well Name") or inpt, file, f"ONELINE!{cols['INPT ID']}{row}",
            inpt_id=inpt, well_name=get("Well Name"), status=get("WELL STATUS"), landing_zone=get("Landing Zone"), county=get("County/Parish"),
            reserves_category=get("Econ PRMS Reserves Category"), first_prod_date=get("First Prod Date"), spud_date=get("Spud Date"), oneline_row=row,
        )
        gold.edge(location, "VALUED_IN", case, "source", file, f"ONELINE!{cols['Project Name']}{row}")
        unit = units.get(norm_name(get("UNIT")))
        if unit:
            gold.edge(location, "ASSIGNED_TO_UNIT", unit, "source", file, f"ONELINE!{cols['UNIT']}{row}", source_value=get("UNIT"))
            gold.alias(unit, str(get("UNIT")), f"{file} UNIT")
        operator_name = get("Current Operator")
        operator = gold.node("Operator", p("Operator"), slug(operator_name), operator_name, file, f"ONELINE!{cols['Current Operator']}{row}", name=operator_name)
        gold.edge(location, "OPERATED_BY", operator, "source", file, f"ONELINE!{cols['Current Operator']}{row}", alias=get("Current Operator Alias"))
        bench = landing.entries.get(str(get("Landing Zone")).strip()) if get("Landing Zone") else None
        if bench:
            gold.edge(location, "TARGETS_ZONE", zone_ids[bench], "alias", file, f"ONELINE!{cols['Landing Zone']}{row}", alias_table="landing_zones", alias_status=landing.status)
        if get("BATTERY"):
            battery = gold.node("BatteryCode", p("BatteryCode"), slug(get("BATTERY")), get("BATTERY"), file, f"ONELINE!{cols['BATTERY']}{row}", code=get("BATTERY"))
            gold.edge(location, "SOLD_THROUGH", battery, "source", file, f"ONELINE!{cols['BATTERY']}{row}")
        api = _api_number(get("API 14"), 14)
        if api and api in wells:
            gold.edge(location, "IS_WELL", wells[api], "key", file, f"ONELINE!{cols['API 14']}{row}", api_14=api)
        for header, (measure, unit_name, factor) in ONELINE_MEASURES.items():
            value = get(header)
            if isinstance(value, (int, float)):
                gold.fact(location, measure, float(value) * factor, unit_name, file, f"ONELINE!{cols[header]}{row}", case_id=case, dataset_id=dataset)


def _cashflow(silver: Silver, gold: Gold, p, asset: str) -> None:
    dataset = "combocurve/cashflow"
    if dataset not in silver.tables:
        return
    file = silver.tables[dataset]["file"]
    headers = silver.tables[dataset]["headers"]
    cols = silver.column_by_header(dataset)
    scope = None
    measure_cols = [c for c, path in headers.items() if col_index(c) > col_index(cols["Date"])]
    for row, values, _ in silver.records(dataset):
        if scope is None:
            group = values.get(cols["Group"]) or "all wells"
            scope = gold.node("ReportingScope", p("ReportingScope"), slug(f"cashflow {group}"), f"Economics cash flow ({group})", file, f"CASHFLOW!{cols['Group']}{row}", name=group, basis="net")
            gold.edge(scope, "REPORTS_ON", asset, "source", file, "CASHFLOW")
        period = str(values.get(cols["Date"]))[:10]
        for column in measure_cols:
            value = values.get(column)
            if isinstance(value, (int, float)):
                gold.fact(scope, "cashflow_value", float(value), _unit_of(headers[column][-1]), file, f"CASHFLOW!{column}{row}", period=period, item=headers[column][-1], dataset_id=dataset)


def _unit_of(header: str) -> str:
    match = re.search(r"\(([^()]+)\)\s*$", header)
    return match.group(1) if match else ""


def _los(silver: Silver, gold: Gold, p, asset: str) -> None:
    for dataset, table in silver.tables.items():
        if table["family"] != "los":
            continue
        file = table["file"]
        context = table["context"]
        months, sections = context["months"], context["sections"]
        tab = context["scope"]
        scope = gold.node("ReportingScope", p("ReportingScope"), slug(tab), tab, file, f"{tab}!A1", name=tab, basis="net" if "NET" in tab.upper() else "gross", title=context.get("title"))
        gold.edge(scope, "REPORTS_ON", asset, "source", file, f"{tab}!A1")
        for row, values, qualities in silver.records(dataset):
            label = values.get("A")
            section = sections.get(str(row)) or "Production"
            if not label or str(label).rstrip(":") == section:
                continue
            for column, month in months.items():
                if column not in values and column not in qualities:
                    continue
                value = values.get(column)
                quality = qualities.get(column, "ok")
                if value is None and quality == "ok":
                    continue
                gold.fact(scope, "los_value", float(value) if isinstance(value, (int, float)) else None, str(values.get("B") or ""), file, f"{tab}!{column}{row}", quality=quality, period=month, item=f"{section}: {label}", section=section, dataset_id=dataset)


def _basis(silver: Silver, gold: Gold, p, asset: str) -> None:
    for dataset, table in silver.tables.items():
        family = table["family"]
        if family not in {"basis", "basis_strip"}:
            continue
        file = table["file"]
        headers = table["headers"]
        period = table["context"]["period"]
        for row, values, _ in silver.records(dataset):
            if family == "basis_strip":
                for column, value in values.items():
                    if column != "C" and isinstance(value, (int, float)):
                        gold.fact(asset, "strip_price", float(value), "$", file, f"{table['sheet']}!{column}{row}", period=str(values["C"])[:10], item=headers.get(column, [column])[-1], section=f"report {period}", dataset_id=dataset)
                continue
            name = values["C"]
            facility = gold.node("PricingFacility", p("PricingFacility"), slug(name), name, file, f"{table['sheet']}!C{row}", name=name, well_type=values.get("E"))
            for column, value in values.items():
                if column not in {"C", "D", "E"} and isinstance(value, (int, float)):
                    path = headers.get(column, [column])
                    gold.fact(facility, "basis_value", float(value), _unit_of(path[0]) if len(path) > 1 else "", file, f"{table['sheet']}!{column}{row}", period=period, item=" > ".join(path), section=table["context"]["section"], dataset_id=dataset)


def _documents(silver: Silver, gold: Gold, p, asset: str) -> None:
    for document in silver.documents:
        for claim in document["claims"]:
            node = gold.node(
                "DocumentClaim", p("DocumentClaim"), claim["claim_id"], f"{claim['label']}: {claim['raw'].split()[-1]}", document["file"], f"page {claim['page']}",
                claim_id=claim["claim_id"], label=claim["label"], value=claim["value"], unit=claim["unit"], page=claim["page"], raw=claim["raw"], file_id=document["file_id"],
            )
            gold.edge(node, "ABOUT", asset, "document", document["file"], f"page {claim['page']}")
