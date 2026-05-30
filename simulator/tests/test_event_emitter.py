"""Tests for simulator/event_emitter.py — every packet must round-trip."""
from ble_protocol import BLEPacket, parse_battery_status, parse_button_pressed, parse_key_pressed
from simulator import event_emitter as emit


def _parse(data: bytes):
    return BLEPacket.parse(data)


def test_keep_alive_reply_opcode():
    op, payload = _parse(emit.keep_alive_reply())
    assert op == 0x81
    assert payload == b""


def test_profile_changed_round_trip():
    op, payload = _parse(emit.profile_changed(3))
    assert op == 0x82
    assert payload[0] == 3


def test_button_pressed_round_trip():
    op, payload = _parse(emit.button_pressed(1, "macro1"))
    assert op == 0x83
    profile_idx, name = parse_button_pressed(payload)
    assert profile_idx == 1
    assert name == "macro1"


def test_key_pressed_round_trip():
    op, payload = _parse(emit.key_pressed(0, "A"))
    assert op == 0x84
    profile_idx, key = parse_key_pressed(payload)
    assert profile_idx == 0
    assert key == "A"


def test_battery_status_percent():
    op, payload = _parse(emit.battery_status(75))
    assert op == 0x85
    assert parse_battery_status(payload) == 75


def test_battery_status_no_battery():
    op, payload = _parse(emit.battery_status(-1))
    assert op == 0x85
    assert payload[0] == 0xFF


def test_battery_status_clamped_at_100():
    _, payload = _parse(emit.battery_status(200))
    assert payload[0] == 100


def test_button_pressed_unicode_name():
    op, payload = _parse(emit.button_pressed(2, "café"))
    _, name = parse_button_pressed(payload)
    assert name == "café"
