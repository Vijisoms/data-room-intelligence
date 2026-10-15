from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import shapefile
from pyproj import CRS, Geod
from shapely import to_wkb
from shapely.geometry import mapping, shape
from shapely.strtree import STRtree

from ..contracts import DatasetSchema, FieldSchema

GEOD = Geod(ellps="WGS84")
SQ_METERS_PER_ACRE = 4046.8564224
DBF_TYPES = {"C": "string", "N": "number", "F": "number", "D": "date", "L": "boolean", "M": "string"}


@dataclass
class Layer:
    dataset_id: str
    file_id: str
    path: str
    name: str
    crs: str
    fields: list[tuple[str, str]]
    records: list[dict[str, Any]]
    geometries: list[Any]
    feature_ids: list[str] = field(default_factory=list)

    @property
    def geometry_type(self) -> str:
        return self.geometries[0].geom_type if self.geometries else "Empty"


def read_layer(path: Path, file_id: str, relative: str) -> Layer:
    prj = path.with_suffix(".prj")
    crs = CRS.from_wkt(prj.read_text(encoding="utf-8")) if prj.exists() else None
    epsg = crs.to_epsg() if crs else None
    if epsg not in (4326, None):
        raise ValueError(f"{relative}: CRS EPSG:{epsg} is not EPSG:4326; reprojection is not implemented")
    with shapefile.Reader(str(path)) as reader:
        fields = [(item[0], DBF_TYPES.get(item[1], "string")) for item in reader.fields[1:]]
        records, geometries = [], []
        for item in reader.iterShapeRecords():
            records.append({key: _clean(value) for key, value in item.record.as_dict().items()})
            geometries.append(shape(item.shape.__geo_interface__))
    layer = Layer(f"{file_id}/{path.stem}", file_id, relative, path.stem, f"EPSG:{epsg or 4326}", fields, records, geometries)
    layer.feature_ids = [_feature_id(record, geometry) for record, geometry in zip(records, geometries)]
    return layer


def _clean(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, str):
        return value.strip()
    return value


def _feature_id(record: dict[str, Any], geometry: Any) -> str:
    for key in ("API_14", "UNIT_NAME", "UNIT"):
        if record.get(key):
            return str(record[key])
    return "g-" + hashlib.sha256(to_wkb(geometry)).hexdigest()[:12]


def geodesic_acres(geometry: Any) -> float:
    area, _ = GEOD.geometry_area_perimeter(geometry)
    return abs(area) / SQ_METERS_PER_ACRE


def geodesic_length_ft(geometry: Any) -> float:
    return GEOD.geometry_length(geometry) * 3.280839895


def layer_schema(layer: Layer) -> DatasetSchema:
    fields = []
    for name, kind in layer.fields:
        values = [record.get(name) for record in layer.records]
        present = [value for value in values if value not in (None, "")]
        if kind == "number" and present and all(float(value).is_integer() for value in present):
            kind = "integer" if not name.upper().startswith(("WI_", "NRI_")) else "number"
        distinct = {str(value) for value in present}
        fields.append(
            FieldSchema(
                field_id=f"{layer.dataset_id}/{name}",
                dataset_id=layer.dataset_id,
                column_ref=name,
                header_path=[name],
                inferred_type=kind if present else "empty",
                scale="fraction (0-1)" if name.upper().startswith(("WI_", "NRI_")) else None,
                rows=len(values),
                null_rate=round(1 - len(present) / len(values), 4) if values else 0.0,
                distinct_count=len(distinct),
                samples=[_json(value) for value in present[:3]],
                candidate_key=bool(present) and len(distinct) == len(values),
            )
        )
    invalid = sum(not geometry.is_valid for geometry in layer.geometries)
    return DatasetSchema(
        dataset_id=layer.dataset_id,
        file=layer.path,
        kind="feature_layer",
        locator=layer.name,
        record_count=len(layer.records),
        fields=fields,
        crs=layer.crs,
        notes=[f"{layer.geometry_type} geometry", f"{invalid} invalid geometries"],
    )


def _json(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def feature_rows(layer: Layer) -> list[dict[str, Any]]:
    rows = []
    for index, (record, geometry, feature_id) in enumerate(zip(layer.records, layer.geometries, layer.feature_ids)):
        polygonal = geometry.geom_type in {"Polygon", "MultiPolygon"}
        rows.append(
            {
                "dataset_id": layer.dataset_id,
                "feature_index": index,
                "feature_id": feature_id,
                "attributes": json.dumps({k: _json(v) for k, v in record.items()}, default=str),
                "wkb": to_wkb(geometry),
                "geodesic_acres": geodesic_acres(geometry) if polygonal else None,
                "geodesic_length_ft": None if polygonal else geodesic_length_ft(geometry),
                "valid": bool(geometry.is_valid),
            }
        )
    return rows


def geojson(layer: Layer, precision: int = 6) -> dict[str, Any]:
    def rounded(coords: Any) -> Any:
        if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
            return [round(value, precision) for value in coords]
        return [rounded(item) for item in coords]

    features = []
    for index, (record, geometry, feature_id) in enumerate(zip(layer.records, layer.geometries, layer.feature_ids)):
        geom = mapping(geometry)
        features.append(
            {
                "type": "Feature",
                "id": index,
                "properties": {"feature_id": feature_id, **{k: _json(v) for k, v in record.items()}},
                "geometry": {"type": geom["type"], "coordinates": rounded(geom["coordinates"])},
            }
        )
    return {"type": "FeatureCollection", "name": layer.name, "features": features}


def spatial_candidates(units: Layer, laterals: Layer, tracts: Layer, units_alt: Layer | None) -> list[dict[str, Any]]:
    """Spatial link candidates between layers; M3 turns accepted ones into relationships."""
    unit_tree = STRtree(units.geometries)
    tract_tree = STRtree(tracts.geometries)
    links: list[dict[str, Any]] = []

    def add(kind: str, a: Layer, i: int, b: Layer, j: int, measure: float | None = None) -> None:
        links.append(
            {
                "kind": kind,
                "source_dataset": a.dataset_id,
                "source_index": i,
                "source_feature": a.feature_ids[i],
                "target_dataset": b.dataset_id,
                "target_index": j,
                "target_feature": b.feature_ids[j],
                "measure": measure,
            }
        )

    for i, line in enumerate(laterals.geometries):
        for j in unit_tree.query(line, predicate="covered_by"):
            add("lateral_in_unit", laterals, i, units, int(j))
        for j in tract_tree.query(line, predicate="intersects"):
            add("lateral_crosses_tract", laterals, i, tracts, int(j), geodesic_length_ft(line.intersection(tracts.geometries[j])))
    for i, polygon in enumerate(tracts.geometries):
        for j in unit_tree.query(polygon, predicate="covered_by"):
            add("tract_within_unit", tracts, i, units, int(j))
    if units_alt is not None:
        by_wkb = {to_wkb(geometry): j for j, geometry in enumerate(units.geometries)}
        for i, geometry in enumerate(units_alt.geometries):
            j = by_wkb.get(to_wkb(geometry))
            if j is None:
                j = next((int(k) for k in unit_tree.query(geometry, predicate="intersects") if geometry.equals(units.geometries[k])), None)
            if j is not None:
                add("same_geometry", units_alt, i, units, j)
    return links
