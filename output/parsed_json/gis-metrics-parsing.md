# GIS metrics parsing

## Output

`gis_metrics.json` contains 4 typed metric records under
`metrics`: `mapped_unit_area`, `active_leasehold_area`, `pdp_lateral_count`, `pdp_laterals_intersecting_leasehold`.

## Calculations

| Metric | Method |
|---|---|
| `mapped_unit_area` | WGS84 geodesic area of dissolved unit polygons, converted from square metres to acres |
| `active_leasehold_area` | WGS84 geodesic area of dissolved leasehold polygons, converted to acres |
| `pdp_lateral_count` | Number of PDP line features |
| `pdp_laterals_intersecting_leasehold` | Count of lateral geometries intersecting dissolved leasehold |

Area is calculated with `pyproj.Geod(ellps="WGS84")`; raw longitude/latitude
degree area is not used. Every metric includes source file provenance and its
calculation method where applicable.
