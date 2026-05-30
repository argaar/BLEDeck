"""Contract test: every ble_protocol builder must be decoded correctly by
``debug/protocol_decoder.py``. Catches drift between the live wire format
and the offline diagnostic tool that operators run when something breaks."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import ble_protocol  # noqa: E402

_DECODER = Path(__file__).parent.parent.parent / "debug" / "protocol_decoder.py"


def _decode(packet: bytes) -> str:
    """Invoke the decoder as a subprocess; return its stdout."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    res = subprocess.run(
        [sys.executable, str(_DECODER), packet.hex()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        env=env,
    )
    assert res.returncode == 0, f"decoder exited {res.returncode}: {res.stderr}"
    return res.stdout


@pytest.mark.parametrize(
    "opcode_name,packet",
    [
        ("KEEP_ALIVE", ble_protocol.keep_alive()),
        ("CHANGE_PROFILE", ble_protocol.change_profile(1, "Test")),
        ("SYNC_PROFILES", ble_protocol.sync_profiles({1: "A", 2: "BB"})),
        ("SET_RGB_KEY", ble_protocol.set_rgb_key(5, 255, 0, 0, 100)),
        (
            "SET_ALL_RGB_KEYS",
            ble_protocol.set_all_rgb_keys([(i, i, i, 50) for i in range(16)]),
        ),
        ("LOCK_DEVICE", ble_protocol.lock_device(True)),
        ("HELLO", ble_protocol.hello("0.2.3")),
    ],
)
def test_decoder_names_every_builder(opcode_name: str, packet: bytes) -> None:
    out = _decode(packet)
    assert opcode_name in out, f"decoder did not label {opcode_name!r} - output:\n{out}"


def test_decoder_decodes_change_profile_fields() -> None:
    packet = ble_protocol.change_profile(2, "Gaming")
    out = _decode(packet)
    assert "Profile Index: 2" in out
    assert "Gaming" in out


def test_decoder_decodes_set_rgb_key_fields() -> None:
    packet = ble_protocol.set_rgb_key(7, 128, 64, 32, 75)
    out = _decode(packet)
    assert "Key Index: 7" in out
    assert "R=128" in out and "G=64" in out and "B=32" in out and "W=75" in out


def test_decoder_decodes_hello_fields() -> None:
    packet = ble_protocol.hello("1.2.3")
    out = _decode(packet)
    assert "Protocol Version: 1" in out
    assert "App Version: '1.2.3'" in out or 'App Version: "1.2.3"' in out
