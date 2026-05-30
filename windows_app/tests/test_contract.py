"""Cross-component contract tests: app builders <-> simulator handler.

The two Python implementations of the BLE protocol must agree on every byte.
A drift between them would surface only on real hardware - these tests pin
the agreement so a builder/handler refactor breaks loudly here first.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make both packages importable.
sys.path.insert(0, str(Path(__file__).parent.parent))                  # windows_app/
sys.path.insert(0, str(Path(__file__).parent.parent.parent))           # repo root

import ble_protocol  # noqa: E402
from simulator import command_handler  # noqa: E402
from simulator._context import reset_state, get_state  # noqa: E402


def _dispatch(raw: bytes) -> list[bytes]:
    """Run a packet through the real handler against the module-global state."""
    return list(command_handler.handle(get_state(), raw))


@pytest.fixture(autouse=True)
def _isolate_state():
    reset_state()
    yield
    reset_state()


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------
def test_change_profile_app_builder_matches_simulator_handler() -> None:
    raw = ble_protocol.change_profile(2, "Gaming")
    _dispatch(raw)
    state = get_state()
    # Simulator stores names keyed by the 1-based wire index.
    assert state.profiles[2] == "Gaming"


def test_change_profile_unicode_name_round_trips() -> None:
    raw = ble_protocol.change_profile(1, "Café")
    _dispatch(raw)
    state = get_state()
    assert state.profiles[1] == "Café"


def test_sync_profiles_round_trip() -> None:
    raw = ble_protocol.sync_profiles({1: "Main", 2: "Dev", 3: "Gaming"})
    _dispatch(raw)
    state = get_state()
    assert state.profiles == {1: "Main", 2: "Dev", 3: "Gaming"}


def test_sync_profiles_replaces_existing() -> None:
    _dispatch(ble_protocol.sync_profiles({1: "Old"}))
    _dispatch(ble_protocol.sync_profiles({1: "New"}))
    state = get_state()
    assert state.profiles == {1: "New"}


# ---------------------------------------------------------------------------
# RGB
# ---------------------------------------------------------------------------
def test_set_rgb_key_single_round_trip() -> None:
    raw = ble_protocol.set_rgb_key(5, 255, 0, 0, 50)
    _dispatch(raw)
    state = get_state()
    assert state.rgb_matrix[5] == (255, 0, 0, 50)


def test_set_all_rgb_keys_round_trip() -> None:
    palette = [(i * 16, 255 - i * 16, i * 8, 50) for i in range(16)]
    raw = ble_protocol.set_all_rgb_keys(palette)
    _dispatch(raw)
    state = get_state()
    assert state.rgb_matrix[0] == (0, 255, 0, 50)
    assert state.rgb_matrix[15] == (240, 15, 120, 50)


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------
def test_lock_device_true() -> None:
    _dispatch(ble_protocol.lock_device(True))
    assert get_state().locked is True


def test_lock_device_false() -> None:
    _dispatch(ble_protocol.lock_device(True))
    _dispatch(ble_protocol.lock_device(False))
    assert get_state().locked is False


# ---------------------------------------------------------------------------
# HELLO triggers TELEMETRY reply
# ---------------------------------------------------------------------------
def test_hello_triggers_device_telemetry_reply() -> None:
    raw = ble_protocol.hello("0.2.3")
    responses = _dispatch(raw)
    assert len(responses) == 1, "device must reply with one telemetry packet"
    op, payload = ble_protocol.BLEPacket.parse(responses[0])
    assert op == ble_protocol.OP_DEVICE_TELEMETRY
    parsed = ble_protocol.parse_device_telemetry(payload)
    assert parsed["protocol_version"] == ble_protocol.PROTOCOL_VERSION
    assert isinstance(parsed["firmware_version"], str)


def test_hello_with_future_protocol_version_still_replies() -> None:
    """Future app speaks v2 - current sim is v1. Telemetry must still come
    back so the app can surface the mismatch and downgrade behaviour."""
    raw = ble_protocol.BLEPacket.build(
        ble_protocol.OP_HELLO,
        bytes([2, 6]) + b"v2.app",  # protocol_version=2, name_len=6
    )
    responses = _dispatch(raw)
    assert responses, "device must reply even on protocol mismatch"
