from __future__ import annotations

from collections import Counter

from .models import CanonicalModel, QAFinding, SourceRef


def reconcile(model: CanonicalModel, spatial_links: list[dict[str, object]]) -> None:
    by_api = {
        str(link["api_14"]): link
        for link in spatial_links
        if link.get("api_14") not in (None, "")
    }
    by_name = {
        str(link["well_name"]).upper(): link
        for link in spatial_links
        if link.get("well_name") not in (None, "")
    }
    matched = 0
    for well in model.wells:
        link = by_api.get(well.api_14 or "") or by_name.get(well.well_name.upper())
        if not link:
            continue
        matched += 1
        mapped_unit = link.get("unit_name")
        if mapped_unit:
            well.unit_key = str(mapped_unit).upper().replace(" ", "_")
    pdp_count = sum(well.status == "PRODUCING" for well in model.wells)
    spatial_count = len(spatial_links)
    if pdp_count != spatial_count:
        model.findings.append(
            QAFinding(
                severity="error",
                code="PDP_COUNT_MISMATCH",
                message=f"ComboCurve has {pdp_count} producing wells but GIS has {spatial_count} PDP laterals.",
            )
        )
    else:
        model.findings.append(
            QAFinding(
                severity="info",
                code="PDP_COUNT_RECONCILED",
                message=f"Producing well count reconciles at {pdp_count} across ComboCurve and GIS.",
            )
        )
        model.findings.append(
            QAFinding(
                severity="warning",
                code="PRICE_SENSITIVITY_UNAVAILABLE",
                message=(
                    "The room contains one economic price case but no location-level oil/gas "
                    "sensitivity grid; scenario sensitivity requires rerunning the economics engine."
                ),
            )
        )
    if matched != spatial_count:
        model.findings.append(
            QAFinding(
                severity="warning",
                code="WELL_KEY_GAPS",
                message=f"Matched {matched} of {spatial_count} GIS laterals to ComboCurve wells.",
            )
        )
    mapped = model.metric("mapped_unit_area")
    contractual = model.metric("gross_acres")
    if mapped and contractual:
        difference = float(mapped.value) - float(contractual.value)
        model.findings.append(
            QAFinding(
                severity="warning",
                code="AREA_DEFINITION_DIFFERENCE",
                message=(
                    f"Mapped unit footprint exceeds contractual gross acres by {difference:,.0f} acres; "
                    "do not substitute geometry area for ownership acreage."
                ),
                sources=mapped.sources + contractual.sources,
            )
        )
    pdf_values = [
        entry["metrics"].get("gross_acres")
        for entry in model.pdf_facts.values()
        if entry["metrics"].get("gross_acres") is not None
    ]
    if contractual and pdf_values:
        delta = abs(float(contractual.value) - float(pdf_values[0]))
        severity = "info" if delta <= 1 else "warning"
        model.findings.append(
            QAFinding(
                severity=severity,
                code="PDF_GROSS_ACRES_CHECK",
                message=f"PDF gross acres differ from the canonical workbook value by {delta:,.2f} acres.",
                sources=contractual.sources,
            )
        )
    unit_counts = Counter(well.unit_key for well in model.wells if well.unit_key)
    if len(unit_counts) < len(model.units):
        model.findings.append(
            QAFinding(
                severity="warning",
                code="UNITS_WITHOUT_WELLS",
                message=(
                    f"{len(model.units) - len(unit_counts)} of {len(model.units)} units have no "
                    "matched economic well/location record."
                ),
            )
        )
    model.findings.append(
        QAFinding(
            severity="warning",
            code="FIMU_CONTRACT_PENDING",
            message=(
                "The generated FIMU case uses the draft canonical adapter contract because an "
                "authoritative FIMU input schema was not supplied."
            ),
            sources=[SourceRef(path=model.data_room, locator="briefing slide 11")],
        )
    )
