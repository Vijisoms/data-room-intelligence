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
    parsed_dir = tmp_path / "parsed_json"
    parsed_dir.mkdir()
    (parsed_dir / "units.json").write_text('{"units": []}', encoding="utf-8")
    (parsed_dir / "wells.json").write_text('{"wells": []}', encoding="utf-8")
    (parsed_dir / "cash_flow.json").write_text('{"cash_flow": []}', encoding="utf-8")
    (parsed_dir / "combo_metrics.json").write_text('{"metrics": []}', encoding="utf-8")
    (parsed_dir / "spatial_links.json").write_text(
        '{"spatial_links": []}', encoding="utf-8"
    )
    (parsed_dir / "gis_metrics.json").write_text('{"metrics": []}', encoding="utf-8")
    (parsed_dir / "production.json").write_text(
        '{"production": []}', encoding="utf-8"
    )
    (parsed_dir / "pdf_facts.json").write_text(
        '{"pdf_facts": {}}', encoding="utf-8"
    )
    (parsed_dir / "pricing.json").write_text('{"pricing": []}', encoding="utf-8")
    (parsed_dir / "unit-details-parsing.md").write_text("# Units", encoding="utf-8")
    (parsed_dir / "metrics-parsing.md").write_text("# Metrics", encoding="utf-8")
    (parsed_dir / "pipeline-finalization.md").write_text(
        "# Pipeline", encoding="utf-8"
    )
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
        latest["artifacts"]["parsed_json/units.json"]
        == "assets/lone-star-basin/runs/20261015T080000Z/parsed_json/units.json"
    )
    assert (
        latest["artifacts"]["parsed_json/wells.json"]
        == "assets/lone-star-basin/runs/20261015T080000Z/parsed_json/wells.json"
    )
    assert (
        latest["artifacts"]["parsed_json/cash_flow.json"]
        == "assets/lone-star-basin/runs/20261015T080000Z/parsed_json/cash_flow.json"
    )
    assert (
        latest["artifacts"]["parsed_json/unit-details-parsing.md"]
        == "assets/lone-star-basin/runs/20261015T080000Z/parsed_json/unit-details-parsing.md"
    )
    assert (
        latest["artifacts"]["parsed_json/production.json"]
        == "assets/lone-star-basin/runs/20261015T080000Z/parsed_json/production.json"
    )
    assert (
        latest["artifacts"]["parsed_json/metrics-parsing.md"]
        == "assets/lone-star-basin/runs/20261015T080000Z/parsed_json/metrics-parsing.md"
    )
    assert (
        latest["artifacts"]["parsed_json/pipeline-finalization.md"]
        == "assets/lone-star-basin/runs/20261015T080000Z/parsed_json/pipeline-finalization.md"
    )
