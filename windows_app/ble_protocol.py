"""
BLEDeck Binary Protocol
=======================

Frame format:  START(1) | OPCODE(1) | LENGTH_H(1) | LENGTH_L(1) | PAYLOAD(N)
  START  = 0xAA
  LENGTH = uint16 big-endian, byte count of PAYLOAD only

PC → Device (commands)
  0x01  KEEP_ALIVE         payload: (none)
  0x02  CHANGE_PROFILE     payload: index(1) + name_len(1) + name(N)
  0x03  SYNC_PROFILES      payload: count(1) + [index(1)+name_len(1)+name(N)]*count
  0x04  SET_RGB_KEY        payload: key_index(1) + R(1) + G(1) + B(1) + W%(1)
  0x05  SET_ALL_RGB_KEYS   payload: 16 × [R(1)+G(1)+B(1)+W%(1)]  = 64 bytes
  0x06  LOCK_DEVICE        payload: flag(1)  0x01=lock  0x00=unlock
  0x07  HELLO              payload: protocol_version(1) + app_version_len(1) + app_version(N)

Device → PC (events)
  0x81  KEEP_ALIVE_REPLY   payload: (none)
  0x82  PROFILE_CHANGED    payload: profile_index(1)  0-based
  0x83  BUTTON_PRESSED     payload: profile_index(1) + name_len(1) + name(N)
  0x84  KEY_PRESSED        payload: profile_index(1) + key_char(1)
  0x85  BATTERY_STATUS     payload: percent(1)  0-100 = %, 0xFF = no battery/USB
  0x86  DEVICE_TELEMETRY   payload: protocol_version(1) + firmware_version_len(1)
                                    + firmware_version(N) + uptime_ms(4 BE)
                                    + reset_reason(1) + free_heap(4 BE)
                                    + ble_error_count(2 BE)
"""

import logging
import struct
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

START_BYTE = 0xAA

# Hard limit on payload size (bytes) — matches firmware MAX_PAYLOAD_LEN in
# protocolparser.h and the simulator's command_handler cap. Any frame
# declaring a length above this is rejected as malformed.
MAX_PAYLOAD_LEN = 256

# Protocol version negotiated via the HELLO/DEVICE_TELEMETRY handshake.
PROTOCOL_VERSION = 1

# Commands (PC → Device)
OP_KEEP_ALIVE        = 0x01
OP_CHANGE_PROFILE    = 0x02
OP_SYNC_PROFILES     = 0x03
OP_SET_RGB_KEY       = 0x04
OP_SET_ALL_RGB_KEYS  = 0x05
OP_LOCK_DEVICE       = 0x06
OP_HELLO             = 0x07

# Events (Device → PC)
OP_KEEP_ALIVE_REPLY  = 0x81
OP_PROFILE_CHANGED   = 0x82
OP_BUTTON_PRESSED    = 0x83
OP_KEY_PRESSED       = 0x84
OP_BATTERY_STATUS    = 0x85
OP_DEVICE_TELEMETRY  = 0x86

RGBW = Tuple[int, int, int, int]

# Maximum UTF-8 byte length for a profile name transmitted over BLE.
# Keeps name_len within the uint8 field and matches the firmware OLED buffer:
# profile_name[40] holds a NUL-terminated string, so at most 39 payload bytes.
_MAX_PROFILE_NAME_BYTES = 39


def _encode_name(name: str) -> bytes:
    """UTF-8 encode name, truncating to _MAX_PROFILE_NAME_BYTES at a code-point boundary.

    Logs a warning when truncation actually drops bytes; we keep behaviour
    safe rather than raising so a slightly oversized name does not crash the
    BLE send path.
    """
    encoded = name.encode("utf-8")
    if len(encoded) <= _MAX_PROFILE_NAME_BYTES:
        return encoded
    truncated = encoded[:_MAX_PROFILE_NAME_BYTES]
    safe = truncated.decode("utf-8", errors="ignore").encode("utf-8")
    logger.warning(
        "Profile name truncated from %d to %d bytes (limit %d)",
        len(encoded), len(safe), _MAX_PROFILE_NAME_BYTES,
    )
    return safe


class BLEPacket:
    @staticmethod
    def build(opcode: int, payload: bytes = b'') -> bytes:
        length = len(payload)
        return struct.pack(">BBH", START_BYTE, opcode, length) + payload

    @staticmethod
    def parse(raw: bytes | bytearray) -> Tuple[int, bytes]:
        if len(raw) < 4:
            raise ValueError("Invalid packet, too short")

        start, opcode, length = struct.unpack(">BBH", raw[:4])
        if start != START_BYTE:
            raise ValueError("Invalid start byte")
        if length > MAX_PAYLOAD_LEN:
            raise ValueError(
                f"Payload length {length} exceeds MAX_PAYLOAD_LEN ({MAX_PAYLOAD_LEN})"
            )
        if len(raw) < 4 + length:
            raise ValueError(
                f"Truncated packet: declared length {length}, got {len(raw) - 4} payload bytes"
            )

        payload = raw[4:4+length]
        return opcode, payload


# ----------------------------
# Packet builders
# ----------------------------
def keep_alive() -> bytes:
    return BLEPacket.build(OP_KEEP_ALIVE)


def lock_device(lock: bool) -> bytes:
    payload = struct.pack("B", 1 if lock else 0)
    return BLEPacket.build(OP_LOCK_DEVICE, payload)


def change_profile(index: int, name: str) -> bytes:
    name_bytes = _encode_name(name)
    payload = struct.pack("BB", index, len(name_bytes))
    payload += name_bytes
    return BLEPacket.build(OP_CHANGE_PROFILE, payload)


def sync_profiles(profiles_dict: Dict[int, str]) -> bytes:
    payload = struct.pack("B", len(profiles_dict))
    for idx, name in profiles_dict.items():
        name_bytes = _encode_name(name)
        payload += struct.pack("BB", idx, len(name_bytes))
        payload += name_bytes
    return BLEPacket.build(OP_SYNC_PROFILES, payload)


def set_rgb_key(key_idx: int, r: int, g: int, b: int, w: int) -> bytes:
    payload = struct.pack("BBBBB", key_idx, r, g, b, w)
    return BLEPacket.build(OP_SET_RGB_KEY, payload)


def set_all_rgb_keys(rgbw_list: list[RGBW]) -> bytes:
    if len(rgbw_list) != 16:
        raise ValueError("Must provide exactly 16 RGBW tuples")

    payload = b''
    for (r, g, b, w) in rgbw_list:
        payload += struct.pack("BBBB", r, g, b, w)

    return BLEPacket.build(OP_SET_ALL_RGB_KEYS, payload)


def hello(app_version: str) -> bytes:
    name_bytes = app_version.encode("utf-8")[:255]
    payload = bytes([PROTOCOL_VERSION, len(name_bytes)]) + name_bytes
    return BLEPacket.build(OP_HELLO, payload)


# ----------------------------
# Parsing helpers
# ----------------------------
def parse_color_string(color_str: str | None) -> RGBW | None:
    """Parse 'R,G,B,W' string into (r, g, b, w) tuple. Return None on failure."""
    if not color_str:
        return None
    try:
        parts = color_str.strip().split(',')
        if len(parts) != 4:
            return None
        values = []
        for p in parts:
            p = p.strip()
            values.append(0 if p == '' else int(p))
        r, g, b, w = values
        return (
            max(0, min(255, r)),
            max(0, min(255, g)),
            max(0, min(255, b)),
            max(0, min(100, w)),
        )
    except (ValueError, AttributeError):
        return None


def parse_profile_changed(payload: bytes) -> int:
    if len(payload) < 1:
        raise ValueError("PROFILE_CHANGED payload too short")
    return payload[0]


def parse_button_pressed(payload: bytes) -> Tuple[int, str]:
    if len(payload) < 2:
        raise ValueError("BUTTON_PRESSED payload too short")
    profile_idx = payload[0]
    name_len = payload[1]
    if len(payload) < 2 + name_len:
        raise ValueError("BUTTON_PRESSED payload truncated")
    button_name = payload[2:2 + name_len].decode("utf-8", errors="replace")
    return profile_idx, button_name


def parse_key_pressed(payload: bytes) -> Tuple[int, str]:
    if len(payload) < 2:
        raise ValueError("KEY_PRESSED payload too short")
    profile_idx = payload[0]
    raw = payload[1]
    # Accept only the 16 hex characters the firmware emits: '0'-'9', 'A'-'F',
    # 'a'-'f'. Anything else is treated as a malformed event.
    if not (
        0x30 <= raw <= 0x39
        or 0x41 <= raw <= 0x46
        or 0x61 <= raw <= 0x66
    ):
        raise ValueError(f"KEY_PRESSED invalid key byte 0x{raw:02X}")
    key_char = chr(raw)
    return profile_idx, key_char


def parse_battery_status(payload: bytes) -> int:
    if len(payload) < 1:
        raise ValueError("BATTERY_STATUS payload too short")
    return payload[0]


def parse_device_telemetry(payload: bytes) -> dict:
    if len(payload) < 2:
        raise ValueError("DEVICE_TELEMETRY payload too short")
    proto = payload[0]
    fw_len = payload[1]
    expected = 2 + fw_len + 4 + 1 + 4 + 2
    if len(payload) < expected:
        raise ValueError(
            f"DEVICE_TELEMETRY truncated: expected {expected} bytes, got {len(payload)}"
        )
    fw_version = payload[2:2 + fw_len].decode("utf-8", errors="replace")
    off = 2 + fw_len
    uptime_ms = int.from_bytes(payload[off:off + 4], "big"); off += 4
    reset_reason = payload[off]; off += 1
    free_heap = int.from_bytes(payload[off:off + 4], "big"); off += 4
    ble_error_count = int.from_bytes(payload[off:off + 2], "big")
    return {
        "protocol_version": proto,
        "firmware_version": fw_version,
        "uptime_ms": uptime_ms,
        "reset_reason": reset_reason,
        "free_heap": free_heap,
        "ble_error_count": ble_error_count,
    }