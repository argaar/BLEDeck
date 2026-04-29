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

Device → PC (events)
  0x81  KEEP_ALIVE_REPLY   payload: (none)
  0x82  PROFILE_CHANGED    payload: profile_index(1)  0-based
  0x83  BUTTON_PRESSED     payload: profile_index(1) + name_len(1) + name(N)
  0x84  KEY_PRESSED        payload: profile_index(1) + key_char(1)
  0x85  BATTERY_STATUS     payload: percent(1)  0-100 = %, 0xFF = no battery/USB
"""

import struct

START_BYTE = 0xAA

# Commands (PC → Device)
OP_KEEP_ALIVE        = 0x01
OP_CHANGE_PROFILE    = 0x02
OP_SYNC_PROFILES     = 0x03
OP_SET_RGB_KEY       = 0x04
OP_SET_ALL_RGB_KEYS  = 0x05
OP_LOCK_DEVICE       = 0x06

# Events (Device → PC)
OP_KEEP_ALIVE_REPLY  = 0x81
OP_PROFILE_CHANGED   = 0x82
OP_BUTTON_PRESSED    = 0x83
OP_KEY_PRESSED       = 0x84
OP_BATTERY_STATUS    = 0x85

class BLEPacket:
    @staticmethod
    def build(opcode, payload=b''):
        length = len(payload)
        return struct.pack(">BBH", START_BYTE, opcode, length) + payload

    @staticmethod
    def parse(raw):
        if len(raw) < 4:
            raise ValueError("Invalid packet, too short")

        start, opcode, length = struct.unpack(">BBH", raw[:4])
        if start != START_BYTE:
            raise ValueError("Invalid start byte")

        payload = raw[4:4+length]
        return opcode, payload

# ----------------------------
# Packet builders
# ----------------------------
def keep_alive():
    return BLEPacket.build(OP_KEEP_ALIVE)

def lock_device(lock: bool):
    payload = struct.pack("B", 1 if lock else 0)
    return BLEPacket.build(OP_LOCK_DEVICE, payload)

def change_profile(index, name):
    # index: 1B
    # name: len + bytes
    # keys: 16 * 4 bytes RGBW
    name_bytes = name.encode("utf-8")
    payload = struct.pack("BB", index, len(name_bytes))
    payload += name_bytes
    return BLEPacket.build(OP_CHANGE_PROFILE, payload)

def sync_profiles(profiles_dict):
    # dict: {index: name}
    payload = struct.pack("B", len(profiles_dict))
    for idx, name in profiles_dict.items():
        name_bytes = name.encode("utf-8")
        payload += struct.pack("BB", idx, len(name_bytes))
        payload += name_bytes
    return BLEPacket.build(OP_SYNC_PROFILES, payload)

def set_rgb_key(key_idx, r, g, b, w):
    payload = struct.pack("BBBBB", key_idx, r, g, b, w)
    return BLEPacket.build(OP_SET_RGB_KEY, payload)

def set_all_rgb_keys(rgbw_list):
    """
    Set all 16 RGB keys at once
    rgbw_list: list of 16 tuples (r, g, b, w)
    """
    if len(rgbw_list) != 16:
        raise ValueError("Must provide exactly 16 RGBW tuples")

    payload = b''
    for (r, g, b, w) in rgbw_list:
        payload += struct.pack("BBBB", r, g, b, w)

    return BLEPacket.build(OP_SET_ALL_RGB_KEYS, payload)

# ----------------------------
# Parsing helpers
# ----------------------------

def parse_change_profile(payload):
    index = payload[0]
    name_len = payload[1]
    name = payload[2:2 + name_len].decode("utf-8")

    offset = 2 + name_len
    keys = []
    for i in range(16):
        r, g, b, w = struct.unpack("BBBB", payload[offset:offset+4])
        keys.append((r, g, b, w))
        offset += 4

    return index, name, keys

def parse_sync_profiles(payload):
    count = payload[0]
    profiles = {}
    offset = 1
    for _ in range(count):
        idx = payload[offset]
        offset += 1
        name_len = payload[offset]
        offset += 1
        name = payload[offset:offset+name_len].decode("utf-8")
        offset += name_len
        profiles[idx] = name
    return profiles

def parse_set_rgb_key(payload):
    """
    Parse rgb color for a specific key
    Returns key with color
    """
    key_idx, r, g, b, w = struct.unpack("BBBBB", payload)
    return key_idx, (r, g, b, w)

def parse_profile_changed(payload):
    """
    Parse profile changed event
    Returns: profile index
    """
    return payload[0]

def parse_button_pressed(payload):
    """
    Parse button pressed event
    Returns: (profile_index, button_name)
    """
    profile_idx = payload[0]
    name_len = payload[1]
    button_name = payload[2:2 + name_len].decode("utf-8")
    return profile_idx, button_name

def parse_key_pressed(payload):
    """
    Parse key pressed event
    Returns: (profile_index, key_char)
    """
    profile_idx = payload[0]
    key_char = chr(payload[1])
    return profile_idx, key_char

def parse_battery_status(payload) -> int:
    """
    Parse battery status event.
    Returns battery percentage (0-100), or 255 if no battery / USB-only.
    """
    return payload[0]
