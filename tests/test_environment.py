import struct
import zlib

from azure.identity import AzureCliCredential, DefaultAzureCredential

from data_room_intelligence.credentials import azure_credential
from data_room_intelligence.doctor import _two_color_png


def test_credential_pins_cli_subscription(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_CLI_SUBSCRIPTION", "example-subscription")
    assert isinstance(azure_credential(), AzureCliCredential)


def test_credential_defaults_for_hosted_runs(monkeypatch) -> None:
    monkeypatch.delenv("AZURE_CLI_SUBSCRIPTION", raising=False)
    assert isinstance(azure_credential(), DefaultAzureCredential)


def test_doctor_checks_the_room_roles(tmp_path) -> None:
    from pathlib import Path

    from data_room_intelligence.doctor import _check_data_room

    room = Path(__file__).parents[1] / "data" / "sample-room"
    assert _check_data_room(room).status == "PASS"
    (tmp_path / "Lone Star Basin Unit Details_vF.xlsx").write_bytes(b"")
    result = _check_data_room(tmp_path)
    assert result.status == "FAIL" and "economics_oneline" in result.detail and "unit_details" not in result.detail


def test_vision_probe_image_is_half_blue_half_yellow() -> None:
    png = _two_color_png()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", png[16:24])
    length = struct.unpack(">I", png[33:37])[0]
    pixels = zlib.decompress(png[41 : 41 + length])
    row = pixels[1 : 1 + width * 3]
    assert (width, height) == (256, 128)
    assert tuple(row[:3]) == (30, 80, 220)
    assert tuple(row[-3:]) == (250, 210, 20)
