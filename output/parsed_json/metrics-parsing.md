# Canonical metrics derivation

## Initial composition

The pipeline initializes the canonical collection exactly as:

```python
metrics = unit_metrics + combo_metrics + gis_metrics
```

| Metric family | Count | Source |
|---|---:|---|
| Unit Details | 34 | Contractual acreage, ownership, and unit location schedule |
| ComboCurve | 5 | Economic well/location records |
| GIS | 4 | Unit, leasehold, and PDP geometries |
| **Initial parsed metrics** | **43** | Concatenation in the order above |

Metric records share the schema `name`, `value`, `unit`, `dimensions`,
`sources`, and `method`.

## Unit metrics

The unit parser creates `unit_count`, `gross_acres`, `county_count`, and
`development_area_count`, plus `net_acres` and `net_locations` for each of 15
zones. Zone net locations equal the sum of unit gross locations multiplied by
unit WI.

## ComboCurve metrics

The ComboCurve parser creates `economic_location_count`,
`producing_well_count`, `average_wi`, `average_nri`, and
`operated_location_fraction`.

## GIS metrics

The GIS parser creates `mapped_unit_area`, `active_leasehold_area`,
`pdp_lateral_count`, and `pdp_laterals_intersecting_leasehold`.

## Post-reconciliation analytics

After the three parsed lists are assigned, reconciliation adds QA findings but
does not add metrics. `calculate_metrics(model)` then appends
4 analytical metrics in this build: undeveloped WCA gross
location count, undeveloped WCA net locations, undeveloped WCA PV-10, and
latest monthly net production when production records are available.

The final `canonical-model.json` contains 47 metrics. The
standalone `combo_metrics.json` and `gis_metrics.json` remain source-family
outputs and intentionally exclude later analytical metrics.
