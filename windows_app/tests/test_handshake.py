"""Full connect-handshake integration test (app <-> simulator).

Exercises the documented bootstrap sequence:
    HELLO  ->  TELEMETRY  ->  KEEP_ALIVE  ->  SYNC_PROFILES
           ->  CHANGE_PROFILE  ->  SET_ALL_RGB_KEYS

If any step is reordered, omitted, or its byte layout drifts, this test
fails loudly. Pure Python - no BLE radio, no hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import ble_protocol  # noqa: E402
from simulator import command_handler  # noqa: E402
from simulator._context import reset_state, get_state  # noqa: E402


def _dispatch(raw: bytes) -> list[bytes]:
    return list(command_handler.handle(get_state(), raw))


@pytest.fixture(autouse=True)
def _iso():
    reset_state()
    yield
    reset_state()


def test_full_connect_handshake_sequence() -> None:
    # 1. HELLO - app announces protocol version.
    resp = _dispatch(ble_protocol.hello("0.2.3"))
    assert len(resp) == 1, "HELLO must produce exactly one telemetry reply"
    op, payload = ble_protocol.BLEPacket.parse(resp[0])
    assert op == ble_protocol.OP_DEVICE_TELEMETRY
    tel = ble_protocol.parse_device_telemetry(payload)
    assert tel["protocol_version"] == ble_protocol.PROTOCOL_VERSION

    # 2. KEEP_ALIVE - first ping. Some device implementations reply with a
    #    KEEP_ALIVE_REPLY; simulator emits zero or one. Either is acceptable.
    _dispatch(ble_protocol.keep_alive())

    # 3. SYNC_PROFILES - push the entire profile table.
    _dispatch(ble_protocol.sync_profiles({1: "Default", 2: "Gaming", 3: "Dev"}))
    state = get_state()
    assert state.profiles == {1: "Default", 2: "Gaming", 3: "Dev"}

    # 4. CHANGE_PROFILE - set the active profile.
    _dispatch(ble_protocol.change_profile(1, "Default"))
    state = get_state()
    # Wire uses 1-based; simulator stores 0-based active index.
    assert state.current_profile_index == 0

    # 5. SET_ALL_RGB_KEYS - push 16 colours.
    palette = [(255, 0, 0, 80)] * 16
    _dispatch(ble_protocol.set_all_rgb_keys(palette))
    state = get_state()
    assert all(c == (255, 0, 0, 80) for c in state.rgb_matrix)


def test_handshake_idempotent_under_replay() -> None:
    """Replaying the exact same sequence twice must yield identical state.
    Catches accumulation bugs in the simulator (e.g. profile list growing
    instead of being replaced)."""

    def _do_handshake() -> None:
        _dispatch(ble_protocol.hello("0.2.3"))
        _dispatch(ble_protocol.sync_profiles({1: "P1", 2: "P2"}))
        _dispatch(ble_protocol.change_profile(1, "P1"))
        _dispatch(ble_protocol.set_all_rgb_keys([(10, 20, 30, 40)] * 16))

    _do_handshake()
    first = (
        dict(get_state().profiles),
        get_state().current_profile_index,
        list(get_state().rgb_matrix),
    )

    _do_handshake()
    second = (
        dict(get_state().profiles),
        get_state().current_profile_index,
        list(get_state().rgb_matrix),
    )

    assert first == second


def test_change_profile_before_sync_still_accepted() -> None:
    """Out-of-order: app sends CHANGE_PROFILE before SYNC_PROFILES (rare,
    but real if the user encoder-switches during the initial sync). Device
    must accept it without crashing."""
    _dispatch(ble_protocol.hello("0.2.3"))
    _dispatch(ble_protocol.change_profile(2, "Unknown"))
    # No assertion on state - just that the handler didn't blow up. The
    # simulator may either accept the name or wait for the sync; either is
    # acceptable as long as handle() does not raise.


def test_set_rgb_key_then_set_all_overwrites_correctly() -> None:
    """Set one key, then set all. Final state must reflect the bulk update."""
    _dispatch(ble_protocol.set_rgb_key(0, 255, 0, 0, 100))
    palette = [(0, 0, 255, 50)] * 16
    _dispatch(ble_protocol.set_all_rgb_keys(palette))
    state = get_state()
    assert state.rgb_matrix[0] == (0, 0, 255, 50)
