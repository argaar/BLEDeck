import logging
import struct
import simulator  # noqa: F401  trigger sys.path shim

from ble_protocol import (
    BLEPacket,
    OP_KEEP_ALIVE, OP_CHANGE_PROFILE, OP_SYNC_PROFILES,
    OP_SET_RGB_KEY, OP_SET_ALL_RGB_KEYS, OP_LOCK_DEVICE,
    OP_HELLO,
    OP_KEEP_ALIVE_REPLY,
)
from simulator.device_state import DeviceState
from simulator import event_emitter

logger = logging.getLogger(__name__)

# Must match MAX_PAYLOAD_LEN in firmware/src/protocolparser.h.
MAX_PAYLOAD_LEN = 256
# Profile name length cap — matches firmware-side handling.
MAX_PROFILE_NAME_LEN = 39


def handle(state: DeviceState, raw: bytes | bytearray) -> list[bytes]:
    """Parse incoming RX bytes, mutate state, return TX response packets."""
    raw_bytes = bytes(raw)
    # Frame: START(0xAA) | OPCODE(1) | LEN_H(1) | LEN_L(1) | PAYLOAD(N)
    if len(raw_bytes) >= 4:
        declared_len = (raw_bytes[2] << 8) | raw_bytes[3]
        if declared_len > MAX_PAYLOAD_LEN:
            logger.debug("rejecting oversized packet (len=%d): %r", declared_len, raw_bytes)
            return []
        if len(raw_bytes) < 4 + declared_len:
            logger.debug("dropping truncated packet (need %d bytes): %r",
                         4 + declared_len, raw_bytes)
            return []

    try:
        opcode, payload = BLEPacket.parse(raw_bytes)
    except ValueError:
        logger.debug("dropping malformed packet: %r", raw_bytes)
        return []

    if opcode == OP_KEEP_ALIVE:
        return [BLEPacket.build(OP_KEEP_ALIVE_REPLY)]

    if opcode == OP_SYNC_PROFILES:
        _handle_sync_profiles(state, payload)
        return []

    if opcode == OP_CHANGE_PROFILE:
        if len(payload) < 2:
            return []
        # command uses 1-based index; state is 0-based
        idx_1based = payload[0]
        name_len = payload[1]
        if name_len > MAX_PROFILE_NAME_LEN:
            logger.debug("CHANGE_PROFILE name_len=%d exceeds %d; dropping",
                         name_len, MAX_PROFILE_NAME_LEN)
            return []
        if len(payload) < 2 + name_len:
            logger.debug("CHANGE_PROFILE truncated name (need %d bytes): %r",
                         2 + name_len, payload)
            return []
        name = payload[2:2 + name_len].decode("utf-8", errors="replace")
        idx_0based = max(0, idx_1based - 1)
        state.current_profile_index = idx_0based
        if name:
            state.profiles[idx_1based] = name
        return []

    if opcode == OP_SET_RGB_KEY:
        if len(payload) >= 5:
            key_idx, r, g, b, w = struct.unpack_from("BBBBB", payload)
            if 0 <= key_idx < 16:
                state.rgb_matrix[key_idx] = (r, g, b, w)
        return []

    if opcode == OP_SET_ALL_RGB_KEYS:
        if len(payload) >= 64:
            state.rgb_matrix = [
                (payload[i], payload[i + 1], payload[i + 2], payload[i + 3])
                for i in range(0, 64, 4)
            ]
        return []

    if opcode == OP_LOCK_DEVICE:
        if len(payload) >= 1:
            state.locked = payload[0] == 0x01
        return []

    if opcode == OP_HELLO:
        if len(payload) < 2:
            return []
        proto = payload[0]
        name_len = payload[1]
        if len(payload) < 2 + name_len:
            logger.debug("HELLO truncated app_version (need %d bytes): %r",
                         2 + name_len, payload)
            return []
        app_version = payload[2:2 + name_len].decode("utf-8", errors="replace")
        logger.debug("HELLO received: proto=%d app_version=%r", proto, app_version)
        state.last_seen_app_version = app_version
        state.last_seen_protocol_version = proto
        return [event_emitter.device_telemetry()]

    return []


def _handle_sync_profiles(state: DeviceState, payload: bytes) -> None:
    if len(payload) < 1:
        return
    count = payload[0]
    offset = 1
    new_profiles: dict[int, str] = {}
    for _ in range(count):
        if offset + 2 > len(payload):
            break
        idx = payload[offset]
        name_len = payload[offset + 1]
        offset += 2
        if offset + name_len > len(payload):
            break
        name = payload[offset: offset + name_len].decode("utf-8", errors="replace")
        offset += name_len
        new_profiles[idx] = name
    state.profiles = new_profiles
