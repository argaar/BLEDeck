import simulator  # noqa: F401  trigger sys.path shim

from ble_protocol import (
    BLEPacket,
    OP_KEEP_ALIVE_REPLY, OP_PROFILE_CHANGED, OP_BUTTON_PRESSED,
    OP_KEY_PRESSED, OP_BATTERY_STATUS, OP_DEVICE_TELEMETRY,
)


def keep_alive_reply() -> bytes:
    return BLEPacket.build(OP_KEEP_ALIVE_REPLY)


def profile_changed(profile_index: int) -> bytes:
    """profile_index is 0-based."""
    return BLEPacket.build(OP_PROFILE_CHANGED, bytes([profile_index & 0xFF]))


def button_pressed(profile_index: int, name: str) -> bytes:
    """profile_index is 0-based."""
    name_bytes = name.encode("utf-8")
    payload = bytes([profile_index & 0xFF, len(name_bytes)]) + name_bytes
    return BLEPacket.build(OP_BUTTON_PRESSED, payload)


def key_pressed(profile_index: int, key_char: str) -> bytes:
    """profile_index is 0-based; key_char must be a single character."""
    payload = bytes([profile_index & 0xFF, ord(key_char[0]) & 0xFF])
    return BLEPacket.build(OP_KEY_PRESSED, payload)


def battery_status(percent: int) -> bytes:
    """percent: 0-100, or -1 for no-battery/USB (sends 0xFF)."""
    value = 0xFF if percent < 0 else min(100, percent)
    return BLEPacket.build(OP_BATTERY_STATUS, bytes([value & 0xFF]))


def device_telemetry(
    firmware_version: str = "0.0.0-sim",
    uptime_ms: int = 0,
    reset_reason: int = 0,
    free_heap: int = 0,
    ble_error_count: int = 0,
) -> bytes:
    fw_bytes = firmware_version.encode("utf-8")[:255]
    payload = bytes([1, len(fw_bytes)]) + fw_bytes  # protocol_version = 1
    payload += uptime_ms.to_bytes(4, "big")
    payload += bytes([reset_reason])
    payload += free_heap.to_bytes(4, "big")
    payload += ble_error_count.to_bytes(2, "big")
    return BLEPacket.build(OP_DEVICE_TELEMETRY, payload)
