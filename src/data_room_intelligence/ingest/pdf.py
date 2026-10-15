from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from pydantic import BaseModel
from pypdf import PdfReader

from ..config import cache_dirs, offline, slug

DI_API_VERSION = "2024-11-30"
DI_SCOPE = "https://cognitiveservices.azure.com/.default"
CHART_PROMPT_VERSION = "chart-v1"
PAGE_DPI = 96
CROP_DPI = 144
CHART_PROMPT = (
    "You read charts from upstream oil and gas data-room slides. Extract the chart in this "
    "image as data. Read values from data labels when present; otherwise estimate from the "
    "axis and say so in notes. Use the category label as x. If the image is not a chart, set "
    "is_chart to false and leave series empty."
)
VALUE = r"\$?\d[\d,]*(?:\.\d+)?"
LABEL_VALUE = re.compile(rf"^(?P<label>[A-Za-z][A-Za-z0-9 &/().%'$\-]*?)\s+(?P<value>{VALUE})\s*(?P<unit>%|MM|K)?$")
VALUE_ONLY = re.compile(rf"^(?P<value>{VALUE})\s*(?P<unit>%|MM|K)?$")
DATE_SUFFIX = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December|Q[1-4])$", re.I)
SKIP_ROLES = {"pageFooter", "pageHeader", "pageNumber", "title", "sectionHeading"}


class Point(BaseModel):
    x: str
    y: float | None


class Series(BaseModel):
    name: str
    points: list[Point]


class ChartExtraction(BaseModel):
    is_chart: bool
    chart_type: str
    title: str | None
    x_axis: str | None
    y_axis: str | None
    unit: str | None
    series: list[Series]
    notes: str | None


def _cache_get(kind: str, key: str) -> Any:
    for root in cache_dirs():
        path = root / kind / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text("utf-8"))
    return None


def _cache_put(kind: str, key: str, value: Any) -> None:
    path = cache_dirs()[0] / kind / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _request(url: str, token: str, data: bytes | None = None, content_type: str | None = None):
    headers = {"Authorization": f"Bearer {token}", **({"Content-Type": content_type} if content_type else {})}
    for attempt in range(6):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=120)  # noqa: S310
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 5:
                raise
            time.sleep(int(error.headers.get("Retry-After", "5")))
    raise RuntimeError("unreachable")


def layout(path: Path, sha256: str, endpoint: str | None, credential: Any) -> tuple[dict[str, Any], str]:
    """Document Intelligence prebuilt-layout result (cached by content hash), else native text."""
    cached = _cache_get("di", sha256)
    if cached:
        return cached, "document-intelligence (cached)"
    if offline() or not endpoint or credential is None:
        return _native_layout(path), "native text (offline)"
    if not endpoint.startswith("https://"):
        raise ValueError("DOC_INTELLIGENCE_ENDPOINT must be https")
    token = credential.get_token(DI_SCOPE).token
    url = f"{endpoint.rstrip('/')}/documentintelligence/documentModels/prebuilt-layout:analyze?api-version={DI_API_VERSION}"
    with _request(url, token, data=path.read_bytes(), content_type="application/pdf") as response:
        operation = response.headers["Operation-Location"]
    while True:
        time.sleep(2)
        with _request(operation, token) as response:
            payload = json.load(response)
        if payload["status"] in {"succeeded", "failed"}:
            break
    if payload["status"] != "succeeded":
        raise RuntimeError(f"layout failed for {path.name}: {payload.get('error')}")
    result = payload["analyzeResult"]
    _cache_put("di", sha256, result)
    return result, "document-intelligence"


def _native_layout(path: Path) -> dict[str, Any]:
    reader = PdfReader(str(path))
    pages, paragraphs = [], []
    for number, page in enumerate(reader.pages, start=1):
        width, height = float(page.mediabox.width) / 72, float(page.mediabox.height) / 72
        pages.append({"pageNumber": number, "width": width, "height": height, "unit": "inch", "lines": []})
        for text in (page.extract_text() or "").splitlines():
            if text.strip():
                paragraphs.append({"content": text.strip(), "boundingRegions": [{"pageNumber": number, "polygon": []}]})
    return {"pages": pages, "paragraphs": paragraphs, "tables": [], "figures": []}


def render_pages(path: Path, out_dir: Path, dpi: int = PAGE_DPI) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(str(path))
    names = []
    try:
        for index in range(len(document)):
            name = f"page-{index + 1}.png"
            document[index].render(scale=dpi / 72).to_pil().save(out_dir / name)
            names.append(name)
    finally:
        document.close()
    return names


def crop_figure(path: Path, page_number: int, polygon: list[float], page_size: tuple[float, float], target: Path) -> str:
    """Own crop from the page; rotated or off-page regions (seen for 45-degree labels) use the whole page."""
    width, height = page_size
    xs, ys = polygon[0::2], polygon[1::2]
    tolerance = 0.05
    aligned = len(xs) == 4 and abs(ys[0] - ys[1]) < tolerance and abs(xs[1] - xs[2]) < tolerance
    inside = bool(xs) and min(xs) >= -tolerance and min(ys) >= -tolerance and max(xs) <= width + tolerance and max(ys) <= height + tolerance
    if aligned and inside:
        box, region = (max(min(xs), 0), max(min(ys), 0), min(max(xs), width), min(max(ys), height)), "figure"
    else:
        box, region = (0, 0, width, height), "page (layout region was rotated or off-page)"
    document = pdfium.PdfDocument(str(path))
    try:
        image = document[page_number - 1].render(scale=CROP_DPI / 72).to_pil()
    finally:
        document.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    image.crop(tuple(int(value * CROP_DPI) for value in box)).save(target)
    return region


async def read_chart(image: bytes, key_basis: str, model: str | None, client_factory: Any) -> tuple[dict[str, Any] | None, str]:
    key = hashlib.sha256(f"{key_basis}|{CHART_PROMPT_VERSION}".encode()).hexdigest()
    cached = _cache_get("vision", key)
    live = not offline() and bool(model) and client_factory is not None
    if cached and (not live or cached.get("model") == model):
        return cached["chart"], f"cached ({cached.get('model')})"
    if not live:
        return None, "not interpreted (offline)"
    from agent_framework import Content, Message

    response = await client_factory(model).get_response(
        [Message("user", [Content.from_text(CHART_PROMPT), Content.from_data(image, "image/png")])],
        options={"response_format": ChartExtraction},
    )
    value = response.value or ChartExtraction.model_validate_json(response.text)
    chart = value.model_dump()
    _cache_put("vision", key, {"model": model, "chart": chart})
    return chart, "interpreted"


def _region(item: dict[str, Any]) -> tuple[int, list[float]]:
    region = (item.get("boundingRegions") or [{"pageNumber": 1, "polygon": []}])[0]
    return region["pageNumber"], region.get("polygon") or []


def _bbox(polygon: list[float]) -> tuple[float, float, float, float] | None:
    if not polygon:
        return None
    return min(polygon[0::2]), min(polygon[1::2]), max(polygon[0::2]), max(polygon[1::2])


def _number(text: str) -> float:
    return float(text.replace("$", "").replace(",", ""))


def extract_claims(file_id: str, paragraphs: list[dict[str, Any]], figure_boxes: dict[int, list[tuple[float, float, float, float]]]) -> list[dict[str, Any]]:
    """Headline numbers (KPI cards): 'Label 123' paragraphs, or a value paragraph under a label."""
    claims: list[dict[str, Any]] = []
    items = []
    for item in paragraphs:
        page, polygon = _region(item)
        box = _bbox(polygon)
        if item.get("role") in SKIP_ROLES or box is None:
            continue
        center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        if any(f[0] <= center[0] <= f[2] and f[1] <= center[1] <= f[3] for f in figure_boxes.get(page, [])):
            continue
        items.append((page, box, polygon, item["content"].strip()))
    labels = [(page, box, text) for page, box, _, text in items if not re.search(r"\d", text)]
    for page, box, polygon, text in items:
        match = LABEL_VALUE.match(text)
        label = match.group("label").strip() if match else None
        if not match and (only := VALUE_ONLY.match(text)):
            above = [
                (box[1] - lb[3], ltext)
                for lpage, lb, ltext in labels
                if lpage == page and -0.05 <= box[1] - lb[3] <= 0.8 and min(box[2], lb[2]) - max(box[0], lb[0]) > 0
            ]
            if above:
                label, match = min(above)[1], only
        if not match or not label:
            continue
        value = _number(match.group("value"))
        if DATE_SUFFIX.search(label.rstrip(" -")) and 1900 <= value <= 2100:
            continue
        unit = match.group("unit") or ("$" if match.group("value").startswith("$") else None)
        claims.append(
            {
                "claim_id": f"{file_id}-p{page}-{slug(label)}",
                "label": label,
                "value": value,
                "unit": unit,
                "raw": text if label in text else f"{label} {text}",
                "page": page,
                "polygon": polygon,
            }
        )
    return claims


async def analyze_document(
    path: Path,
    file_id: str,
    relative: str,
    sha256: str,
    out_dir: Path,
    endpoint: str | None = None,
    credential: Any = None,
    vision_model: str | None = None,
    client_factory: Any = None,
) -> dict[str, Any]:
    result, source = layout(path, sha256, endpoint, credential)
    images = render_pages(path, out_dir / "pages")
    pages = []
    for page, image in zip(result["pages"], images):
        pages.append(
            {
                "page": page["pageNumber"],
                "width": page["width"],
                "height": page["height"],
                "unit": page.get("unit", "inch"),
                "image": f"pages/{image}",
                "lines": [{"content": line["content"], "polygon": line.get("polygon", [])} for line in page.get("lines", [])],
            }
        )
    sizes = {page["page"]: (page["width"], page["height"]) for page in pages}
    figures, boxes = [], {}
    for figure in result.get("figures", []):
        page_number, polygon = _region(figure)
        target = out_dir / "figures" / f"figure-{figure['id']}.png"
        crop = crop_figure(path, page_number, polygon, sizes[page_number], target)
        box = _bbox(polygon) if crop == "figure" else (0, 0, *sizes[page_number])
        boxes.setdefault(page_number, []).append(box)
        started = time.perf_counter()
        chart, status = await read_chart(target.read_bytes(), f"{sha256}|{figure['id']}|{crop}", vision_model, client_factory)
        figures.append(
            {
                "id": figure["id"],
                "page": page_number,
                "polygon": polygon,
                "image": f"figures/{target.name}",
                "crop": crop,
                "chart": chart,
                "status": status,
                "model": vision_model,
                "seconds": round(time.perf_counter() - started, 1),
            }
        )
    paragraphs = []
    for item in result.get("paragraphs", []):
        page_number, polygon = _region(item)
        paragraphs.append({"role": item.get("role"), "content": item["content"], "page": page_number, "polygon": polygon})
    document = {
        "file": relative,
        "file_id": file_id,
        "source": source,
        "model": "prebuilt-layout" if source.startswith("document-intelligence") else "pypdf",
        "api_version": DI_API_VERSION,
        "pages": pages,
        "paragraphs": paragraphs,
        "tables": [
            {"rows": t["rowCount"], "columns": t["columnCount"], "cells": [[c["rowIndex"], c["columnIndex"], c["content"]] for c in t["cells"]], "page": _region(t)[0]}
            for t in result.get("tables", [])
        ],
        "figures": figures,
        "claims": extract_claims(file_id, result.get("paragraphs", []), boxes),
    }
    (out_dir / "document.json").write_text(json.dumps(document, indent=1), encoding="utf-8")
    return document
