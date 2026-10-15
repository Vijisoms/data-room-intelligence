from __future__ import annotations

import base64
import json
import os
import struct
import time
import urllib.error
import urllib.request
import zlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from agent_framework import Content, Message
from agent_framework.foundry import FoundryChatClient
from azure.core.credentials import TokenCredential

from .credentials import azure_credential
from .discovery import discover

FOUNDRY_SCOPE = "https://ai.azure.com/.default"
COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
DOC_INTELLIGENCE_API_VERSION = "2024-11-30"
REQUIRED_KINDS = {
    "excel_units",
    "excel_combocurve",
    "excel_basis",
    "excel_los",
    "gis_units",
    "gis_leasehold",
    "gis_pdp",
    "pdf",
}


@dataclass
class Check:
    name: str
    status: str
    detail: str
    seconds: float | None = None


async def run_doctor(data_room: Path) -> list[Check]:
    checks = [_check_data_room(data_room)]
    credential = azure_credential()
    checks.append(_check_identity(credential))
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    chat_model = os.environ.get("FOUNDRY_MODEL", "").strip()
    vision_model = os.environ.get("FOUNDRY_VISION_MODEL", "").strip()
    checks.append(await _check_chat(endpoint, chat_model, credential))
    checks.append(await _check_vision(endpoint, vision_model, credential))
    checks.append(
        _check_document_intelligence(
            os.environ.get("DOC_INTELLIGENCE_ENDPOINT", "").strip(), credential
        )
    )
    return checks


def format_checks(checks: list[Check]) -> str:
    width = max(len(check.name) for check in checks)
    lines = []
    for check in checks:
        timing = f" ({check.seconds:.1f}s)" if check.seconds is not None else ""
        lines.append(f"{check.status:<4}  {check.name:<{width}}  {check.detail}{timing}")
    return "\n".join(lines)


def _check_data_room(data_room: Path) -> Check:
    if not data_room.is_dir():
        return Check("data room", "FAIL", f"{data_room} is not a directory")
    kinds = Counter(record.kind for record in discover(data_room))
    missing = sorted(REQUIRED_KINDS - set(kinds))
    detail = f"{sum(kinds.values())} files in {data_room}"
    if missing:
        return Check("data room", "FAIL", f"{detail}; missing {', '.join(missing)}")
    return Check("data room", "PASS", detail)


def _check_identity(credential: TokenCredential) -> Check:
    name = type(credential).__name__
    try:
        token = credential.get_token(FOUNDRY_SCOPE).token
    except Exception as error:  # noqa: BLE001 - reported to the operator
        return Check("Azure identity", "FAIL", f"{name}: {_first_line(error)}")
    claims = _jwt_claims(token)
    who = claims.get("upn") or claims.get("unique_name") or claims.get("appid") or "unknown"
    return Check("Azure identity", "PASS", f"{name}; tenant {claims.get('tid')}; {who}")


async def _check_chat(endpoint: str, model: str, credential: TokenCredential) -> Check:
    if not endpoint or not model:
        return Check("Foundry chat", "SKIP", "set FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL")
    client = FoundryChatClient(project_endpoint=endpoint, model=model, credential=credential)
    start = time.perf_counter()
    try:
        response = await client.get_response([Message("user", ["Reply with exactly: OK"])])
    except Exception as error:  # noqa: BLE001 - reported to the operator
        return Check("Foundry chat", "FAIL", f"{model}: {_first_line(error)}")
    text = (response.text or "").strip()
    status = "PASS" if text.upper().startswith("OK") else "FAIL"
    return Check("Foundry chat", status, f"{model} replied {text[:40]!r}", time.perf_counter() - start)


async def _check_vision(endpoint: str, model: str, credential: TokenCredential) -> Check:
    if not endpoint or not model:
        return Check("Foundry vision", "SKIP", "set FOUNDRY_VISION_MODEL")
    client = FoundryChatClient(project_endpoint=endpoint, model=model, credential=credential)
    prompt = (
        "The image has a left half and a right half. Name the color of each half, "
        "left first, as two lowercase words separated by one space."
    )
    start = time.perf_counter()
    try:
        response = await client.get_response(
            [
                Message(
                    "user",
                    [Content.from_text(prompt), Content.from_data(_two_color_png(), "image/png")],
                )
            ]
        )
    except Exception as error:  # noqa: BLE001 - reported to the operator
        return Check("Foundry vision", "FAIL", f"{model}: {_first_line(error)}")
    text = (response.text or "").strip().lower()
    passed = "blue" in text and "yellow" in text and text.index("blue") < text.index("yellow")
    return Check(
        "Foundry vision",
        "PASS" if passed else "FAIL",
        f"{model} read the test image as {text[:40]!r}",
        time.perf_counter() - start,
    )


def _check_document_intelligence(endpoint: str, credential: TokenCredential) -> Check:
    if not endpoint:
        return Check("Document Intelligence", "SKIP", "set DOC_INTELLIGENCE_ENDPOINT")
    if not endpoint.startswith("https://"):
        return Check("Document Intelligence", "FAIL", "endpoint must start with https://")
    url = (
        f"{endpoint.rstrip('/')}/documentintelligence/info"
        f"?api-version={DOC_INTELLIGENCE_API_VERSION}"
    )
    start = time.perf_counter()
    try:
        token = credential.get_token(COGNITIVE_SERVICES_SCOPE).token
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - https only
            payload = json.load(response)
            status_code = response.status
    except urllib.error.HTTPError as error:
        return Check("Document Intelligence", "FAIL", f"HTTP {error.code} {error.reason}")
    except Exception as error:  # noqa: BLE001 - reported to the operator
        return Check("Document Intelligence", "FAIL", _first_line(error))
    models = payload.get("customDocumentModels", {})
    return Check(
        "Document Intelligence",
        "PASS",
        f"HTTP {status_code}; API {DOC_INTELLIGENCE_API_VERSION}; "
        f"custom models {models.get('count')}/{models.get('limit')}",
        time.perf_counter() - start,
    )


def _two_color_png(width: int = 256, height: int = 128) -> bytes:
    # Vision models misread very small images (64x32 was read as solid yellow).
    half = width // 2
    row = b"\x00" + bytes((30, 80, 220)) * half + bytes((250, 210, 20)) * (width - half)

    def chunk(tag: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def _jwt_claims(token: str) -> dict[str, object]:
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


def _first_line(error: Exception) -> str:
    text = str(error).strip().splitlines()
    return f"{type(error).__name__}: {text[0][:200] if text else ''}"
