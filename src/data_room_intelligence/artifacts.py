from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Protocol

from azure.core.credentials import TokenCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

ARTIFACT_CONTENT_TYPES = {
    "canonical-model.json": "application/json",
    "units.json": "application/json",
    "standard-answers.json": "application/json",
    "qa-findings.json": "application/json",
    "fimu-case.json": "application/json",
    "well-unit-links.csv": "text/csv",
    "insight-report.md": "text/markdown",
}
REQUIRED_QUERY_ARTIFACTS = (
    "canonical-model.json",
    "standard-answers.json",
    "qa-findings.json",
)
_ASSET_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class ArtifactReader(Protocol):
    def read_text(self, name: str) -> str: ...


class LocalArtifactReader:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def read_text(self, name: str) -> str:
        return (self.output_dir / name).read_text(encoding="utf-8")


class BlobArtifactReader:
    def __init__(
        self,
        account_url: str,
        container: str,
        asset_id: str,
        credential: TokenCredential,
        manifest_cache_seconds: float = 60,
    ) -> None:
        _validate_asset_id(asset_id)
        self.container_client = BlobServiceClient(
            account_url=account_url,
            credential=credential,
        ).get_container_client(container)
        self.latest_blob = f"assets/{asset_id}/latest.json"
        self.manifest_cache_seconds = manifest_cache_seconds
        self._manifest: dict[str, object] | None = None
        self._manifest_loaded_at = 0.0

    def read_text(self, name: str) -> str:
        manifest = self._load_manifest()
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict) or name not in artifacts:
            raise FileNotFoundError(
                f"Artifact {name!r} is not present in {self.latest_blob}."
            )
        blob_name = artifacts[name]
        if not isinstance(blob_name, str):
            raise ValueError(f"Invalid blob path for artifact {name!r}.")
        return self.container_client.download_blob(blob_name).readall().decode("utf-8")

    def _load_manifest(self) -> dict[str, object]:
        now = monotonic()
        if (
            self._manifest is None
            or now - self._manifest_loaded_at >= self.manifest_cache_seconds
        ):
            payload = self.container_client.download_blob(self.latest_blob).readall()
            manifest = json.loads(payload)
            if not isinstance(manifest, dict):
                raise ValueError(f"{self.latest_blob} must contain a JSON object.")
            self._manifest = manifest
            self._manifest_loaded_at = now
        return self._manifest


class BlobArtifactPublisher:
    def __init__(
        self,
        account_url: str,
        container: str,
        credential: TokenCredential,
    ) -> None:
        self.container_client = BlobServiceClient(
            account_url=account_url,
            credential=credential,
        ).get_container_client(container)

    def publish(
        self,
        output_dir: Path,
        asset_id: str,
        run_id: str | None = None,
    ) -> dict[str, object]:
        _validate_asset_id(asset_id)
        output_dir = output_dir.resolve()
        missing = [
            name for name in REQUIRED_QUERY_ARTIFACTS if not (output_dir / name).is_file()
        ]
        if missing:
            raise FileNotFoundError(
                f"Cannot publish {output_dir}; missing: {', '.join(missing)}"
            )

        published_at = datetime.now(timezone.utc)
        effective_run_id = run_id or published_at.strftime("%Y%m%dT%H%M%SZ")
        run_prefix = f"assets/{asset_id}/runs/{effective_run_id}"
        artifacts: dict[str, str] = {}
        sha256: dict[str, str] = {}

        for name, content_type in ARTIFACT_CONTENT_TYPES.items():
            path = output_dir / name
            if not path.is_file():
                continue
            payload = path.read_bytes()
            blob_name = f"{run_prefix}/{name}"
            self.container_client.upload_blob(
                name=blob_name,
                data=payload,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
                metadata={
                    "asset_id": asset_id,
                    "run_id": effective_run_id,
                    "artifact": name,
                },
            )
            artifacts[name] = blob_name
            sha256[name] = hashlib.sha256(payload).hexdigest()

        canonical = json.loads((output_dir / "canonical-model.json").read_text("utf-8"))
        manifest: dict[str, object] = {
            "schema_version": "1.0",
            "asset_id": asset_id,
            "asset_name": canonical.get("asset_name"),
            "run_id": effective_run_id,
            "published_at": published_at.isoformat(),
            "run_prefix": run_prefix,
            "artifacts": artifacts,
            "sha256": sha256,
        }
        manifest_payload = json.dumps(manifest, indent=2).encode("utf-8")
        settings = ContentSettings(content_type="application/json")
        self.container_client.upload_blob(
            name=f"{run_prefix}/manifest.json",
            data=manifest_payload,
            overwrite=True,
            content_settings=settings,
        )
        self.container_client.upload_blob(
            name=f"assets/{asset_id}/latest.json",
            data=manifest_payload,
            overwrite=True,
            content_settings=settings,
        )
        return manifest


def _validate_asset_id(asset_id: str) -> None:
    if not _ASSET_ID.fullmatch(asset_id):
        raise ValueError(
            "asset_id must be 1-63 lowercase letters, numbers, or hyphens and "
            "must start and end with a letter or number."
        )
