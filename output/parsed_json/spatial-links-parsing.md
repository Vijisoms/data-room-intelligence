# Spatial well-to-unit link parsing

## Sources

- September unit polygons
- September leasehold polygons
- September PDP lateral line features

The shapefile attribute rows and geometries are read in matching order.

## Output

`spatial_links.json` contains 320 records under
`spatial_links`. The same records are also written to `well-unit-links.csv`.

## Matching algorithm

For each PDP lateral, the parser:

1. Finds every unit polygon intersecting the lateral.
2. Measures the geometry intersection length for every candidate.
3. Selects the unit having the maximum intersection length.
4. Tests whether the lateral intersects the dissolved leasehold geometry.

## Schema

| Field | Source or derivation |
|---|---|
| `api_10` | PDP shapefile `API_10`, zero-padded digit text |
| `api_14` | PDP shapefile `API_14`, zero-padded digit text |
| `well_name` | PDP shapefile `Well_Name` |
| `landing_zone` | PDP shapefile `Landing_Zo` |
| `unit_name` | Selected intersecting unit polygon `UNIT_NAME` |
| `unit_key` | `unit_name` normalized like Unit Details keys |
| `intersects_leasehold` | Boolean spatial intersection with dissolved leasehold |

An unmatched lateral has a null `unit_name`.
