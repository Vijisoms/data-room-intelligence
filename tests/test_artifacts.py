import json
from pathlib import Path

from data_room_intelligence.artifacts import BlobArtifactPublisher, LocalArtifactReader


class FakeContainerClient:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def upload_blob(self, name: str, data: bytes, **_: object) -> None:
        self.blobs[name] = data


def test_local_artifact_reader(tmp_path: Path) -> None:
    (tmp_path / "standard-answers.json").write_text('{"answer": 42}', encoding="utf-8")
    reader = LocalArtifactReader(tmp_path)
    assert json.loads(reader.read_text("standard-answers.json")) == {"answer": 42}


def test_blob_publisher_writes_versioned_artifacts_and_latest_manifest(
    tmp_path: Path,
) -> None:
    canonical = {"asset_name": "Lone Star Basin", "metrics": []}
    (tmp_path / "canonical-model.json").write_text(json.dumps(canonical), encoding="utf-8")
    (tmp_path / "units.json").write_text('{"units": []}', encoding="utf-8")
    (tmp_path / "standard-answers.json").write_text("{}", encoding="utf-8")
    (tmp_path / "qa-findings.json").write_text("[]", encoding="utf-8")

    publisher = BlobArtifactPublisher.__new__(BlobArtifactPublisher)
    publisher.container_client = FakeContainerClient()
    manifest = publisher.publish(
        tmp_path,
        asset_id="lone-star-basin",
        run_id="20261015T080000Z",
    )

    latest = json.loads(
        publisher.container_client.blobs["assets/lone-star-basin/latest.json"]
    )
    assert latest == manifest
    assert latest["asset_name"] == "Lone Star Basin"
    assert (
        latest["artifacts"]["canonical-model.json"]
        == "assets/lone-star-basin/runs/20261015T080000Z/canonical-model.json"
    )
    assert len(latest["sha256"]["canonical-model.json"]) == 64
    assert (
        latest["artifacts"]["units.json"]
        == "assets/lone-star-basin/runs/20261015T080000Z/units.json"
    )
