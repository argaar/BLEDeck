"""Tests for simulator/command_handler.py"""
import struct
import pytest

from ble_protocol import (
    BLEPacket,
    OP_KEEP_ALIVE_REPLY,
    OP_DEVICE_TELEMETRY,
    parse_device_telemetry,
)
from simulator.device_state import DeviceState
from simulator.command_handler import handle


def _build(opcode: int, payload: bytes = b"") -> bytes:
    return BLEPacket.build(opcode, payload)


# ─── KEEP_ALIVE ────────────────────────────────────────────────────────────────

def test_keep_alive_returns_reply():
    state = DeviceState()
    resp = handle(state, _build(0x01))
    assert len(resp) == 1
    op, payload = BLEPacket.parse(resp[0])
    assert op == OP_KEEP_ALIVE_REPLY
    assert payload == b""


# ─── SYNC_PROFILES ─────────────────────────────────────────────────────────────

def test_sync_profiles_stores_profiles():
    state = DeviceState()
    name = b"Work"
    payload = bytes([2])  # count=2
    payload += bytes([1, len(b"Work")]) + b"Work"
    payload += bytes([2, len(b"Gaming")]) + b"Gaming"
    resp = handle(state, _build(0x03, payload))
    assert resp == []
    assert state.profiles == {1: "Work", 2: "Gaming"}


def test_sync_profiles_empty():
    state = DeviceState()
    handle(state, _build(0x03, bytes([0])))
    assert state.profiles == {}


# ─── CHANGE_PROFILE ────────────────────────────────────────────────────────────

def test_change_profile_converts_1based_to_0based():
    state = DeviceState()
    name = b"Work"
    payload = bytes([3, len(name)]) + name  # index=3 (1-based), name="Work"
    handle(state, _build(0x02, payload))
    assert state.current_profile_index == 2
    assert state.profiles[3] == "Work"


def test_change_profile_index_1_gives_0():
    state = DeviceState()
    name = b"Default"
    payload = bytes([1, len(name)]) + name
    handle(state, _build(0x02, payload))
    assert state.current_profile_index == 0
    assert state.profiles[1] == "Default"


def test_change_profile_empty_name_does_not_overwrite():
    state = DeviceState()
    state.profiles[2] = "Existing"
    payload = bytes([2, 0])  # empty name
    handle(state, _build(0x02, payload))
    assert state.current_profile_index == 1
    assert state.profiles[2] == "Existing"


def test_change_profile_name_len_too_long_ignored():
    state = DeviceState()
    payload = bytes([1, 200]) + b"A" * 200  # 200 > MAX_PROFILE_NAME_LEN (39)
    handle(state, _build(0x02, payload))
    assert state.current_profile_index == 0
    assert state.profiles == {}


def test_change_profile_truncated_name_ignored():
    state = DeviceState()
    # declares 10-byte name but only supplies 3
    payload = bytes([1, 10]) + b"abc"
    handle(state, _build(0x02, payload))
    assert state.current_profile_index == 0
    assert state.profiles == {}


# ─── SET_RGB_KEY ───────────────────────────────────────────────────────────────

def test_set_rgb_key_updates_matrix():
    state = DeviceState()
    payload = bytes([5, 255, 128, 0, 50])  # key 5, R=255 G=128 B=0 W=50
    handle(state, _build(0x04, payload))
    assert state.rgb_matrix[5] == (255, 128, 0, 50)


def test_set_rgb_key_out_of_range_ignored():
    state = DeviceState()
    payload = bytes([20, 255, 0, 0, 0])  # key 20 — out of range
    handle(state, _build(0x04, payload))
    # no exception, state unchanged
    assert all(c == (0, 0, 0, 0) for c in state.rgb_matrix)


# ─── SET_ALL_RGB_KEYS ──────────────────────────────────────────────────────────

def test_set_all_rgb_keys_replaces_matrix():
    state = DeviceState()
    rgbw = [(i, i, i, 0) for i in range(16)]
    payload = b"".join(struct.pack("BBBB", r, g, b, w) for r, g, b, w in rgbw)
    handle(state, _build(0x05, payload))
    assert state.rgb_matrix == rgbw


def test_set_all_rgb_keys_short_payload_ignored():
    state = DeviceState()
    handle(state, _build(0x05, bytes(32)))  # too short
    assert all(c == (0, 0, 0, 0) for c in state.rgb_matrix)


# ─── LOCK_DEVICE ───────────────────────────────────────────────────────────────

def test_lock_device_sets_locked():
    state = DeviceState()
    handle(state, _build(0x06, bytes([0x01])))
    assert state.locked is True


def test_unlock_device():
    state = DeviceState(locked=True)
    handle(state, _build(0x06, bytes([0x00])))
    assert state.locked is False


# ─── UNKNOWN / MALFORMED ───────────────────────────────────────────────────────

def test_unknown_opcode_returns_empty():
    state = DeviceState()
    resp = handle(state, _build(0xFF))
    assert resp == []


def test_malformed_packet_returns_empty():
    state = DeviceState()
    resp = handle(state, b"\x00\x01")  # too short
    assert resp == []


# ─── HELLO / DEVICE_TELEMETRY ──────────────────────────────────────────────────

def test_hello_triggers_device_telemetry_response():
    state = DeviceState()
    app_ver = b"1.2.3"
    payload = bytes([1, len(app_ver)]) + app_ver
    resp = handle(state, _build(0x07, payload))
    assert len(resp) == 1
    op, telemetry_payload = BLEPacket.parse(resp[0])
    assert op == OP_DEVICE_TELEMETRY
    parsed = parse_device_telemetry(telemetry_payload)
    assert parsed["protocol_version"] == 1
    assert parsed["firmware_version"]  # non-empty
    assert state.last_seen_app_version == "1.2.3"
    assert state.last_seen_protocol_version == 1


def test_hello_truncated_payload_dropped():
    state = DeviceState()
    # Declares 10-byte app_version, supplies only 3 bytes.
    payload = bytes([1, 10]) + b"abc"
    resp = handle(state, _build(0x07, payload))
    assert resp == []


def test_hello_too_short_header_dropped():
    state = DeviceState()
    resp = handle(state, _build(0x07, b"\x01"))  # only 1 byte payload
    assert resp == []
