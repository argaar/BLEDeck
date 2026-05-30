#!/usr/bin/env python3
"""
BLE Protocol Decoder and Analyzer
This script decodes binary packets from the BLEDeck protocol and explains all operations.
"""

import struct
import sys

# Force UTF-8 on stdout/stderr so the unicode glyphs below (✓, ➤, ❌)
# render correctly on Windows consoles defaulting to cp1252.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass

# Protocol constants
START_BYTE = 0xAA
PROTOCOL_VERSION = 1

# Opcodes - Commands (Python → Arduino)
OP_KEEP_ALIVE        = 0x01
OP_CHANGE_PROFILE    = 0x02
OP_SYNC_PROFILES     = 0x03
OP_SET_RGB_KEY       = 0x04
OP_SET_ALL_RGB_KEYS  = 0x05
OP_LOCK_DEVICE       = 0x06
OP_HELLO             = 0x07

# Opcodes - Events (Arduino → Python)
OP_KEEP_ALIVE_REPLY  = 0x81
OP_PROFILE_CHANGED   = 0x82
OP_BUTTON_PRESSED    = 0x83
OP_KEY_PRESSED       = 0x84
OP_BATTERY_STATUS    = 0x85
OP_DEVICE_TELEMETRY  = 0x86

OPCODE_NAMES = {
    0x01: "KEEP_ALIVE",
    0x02: "CHANGE_PROFILE",
    0x03: "SYNC_PROFILES",
    0x04: "SET_RGB_KEY",
    0x05: "SET_ALL_RGB_KEYS",
    0x06: "LOCK_DEVICE",
    0x07: "HELLO",
    0x81: "KEEP_ALIVE_REPLY",
    0x82: "PROFILE_CHANGED",
    0x83: "BUTTON_PRESSED",
    0x84: "KEY_PRESSED",
    0x85: "BATTERY_STATUS",
    0x86: "DEVICE_TELEMETRY",
}

# esp_reset_reason() values (subset — see ESP-IDF docs for full set)
RESET_REASON_NAMES = {
    0: "UNKNOWN",
    1: "POWERON",
    3: "SW",
    5: "DEEPSLEEP",
    6: "BROWNOUT",
    8: "TASK_WDT",
    9: "INT_WDT",
}

def decode_packet(hex_string):
    """
    Decode a hex string into a binary packet and explain all operations.

    Args:
        hex_string: Hex string like "aa010000" or "AA 01 00 00"
    """
    # Clean up hex string
    hex_string = hex_string.replace(" ", "").replace("0x", "").strip()

    try:
        data = bytes.fromhex(hex_string)
    except ValueError as e:
        print(f"❌ Invalid hex string: {e}")
        return

    print("=" * 80)
    print("PACKET ANALYSIS")
    print("=" * 80)
    print(f"Raw hex: {data.hex()}")
    print(f"Length: {len(data)} bytes")
    print()

    if len(data) < 4:
        print("❌ Packet too short (minimum 4 bytes required)")
        return

    # Parse header
    start_byte = data[0]
    opcode = data[1]
    length = struct.unpack(">H", data[2:4])[0]  # Big-endian 16-bit

    print("HEADER:")
    print(f"  Start Byte: 0x{start_byte:02X} {'✓' if start_byte == START_BYTE else '✗ INVALID'}")
    print(f"  Opcode:     0x{opcode:02X} - {OPCODE_NAMES.get(opcode, 'UNKNOWN')}")
    print(f"  Length:     {length} bytes (0x{length:04X})")
    print()

    if start_byte != START_BYTE:
        print("❌ Invalid start byte - packet rejected")
        return

    # Extract payload
    payload = data[4:4+length]

    if len(payload) < length:
        print(f"⚠️  Warning: Expected {length} bytes payload, got {len(payload)}")

    print(f"PAYLOAD ({len(payload)} bytes):")
    if payload:
        print(f"  Hex: {payload.hex()}")
        print(f"  Bytes: {' '.join(f'{b:02X}' for b in payload)}")
    else:
        print("  (empty)")
    print()

    # Decode payload based on opcode
    print("DECODED PAYLOAD:")
    decode_payload(opcode, payload)
    print()


def decode_payload(opcode, payload):
    """Decode payload based on opcode and explain the data."""

    if opcode == OP_KEEP_ALIVE:
        print("  ➤ Keep Alive (Ping)")
        print("    No payload - simple ping to keep connection alive")

    elif opcode == OP_KEEP_ALIVE_REPLY:
        print("  ➤ Keep Alive Reply (Pong)")
        print("    No payload - acknowledgment of ping")

    elif opcode == OP_CHANGE_PROFILE:
        print("  ➤ Change Profile")
        if len(payload) < 2:
            print("    ❌ Payload too short")
            return

        profile_idx = payload[0]
        name_len = payload[1]
        print(f"    Profile Index: {profile_idx} (1-based, per protocol)")
        print(f"    Name Length: {name_len} bytes")

        if len(payload) < 2 + name_len:
            print("    ❌ Payload too short for name")
            return

        name = payload[2:2+name_len].decode("utf-8", errors="replace")
        print(f"    Profile Name: '{name}'")

    elif opcode == OP_SYNC_PROFILES:
        print("  ➤ Sync Profiles")
        if len(payload) < 1:
            print("    ❌ Payload too short")
            return

        count = payload[0]
        print(f"    Profile Count: {count}")

        offset = 1
        for i in range(count):
            if offset + 2 > len(payload):
                print(f"    ⚠️  Truncated at profile {i}")
                break

            idx = payload[offset]
            name_len = payload[offset + 1]
            offset += 2

            if offset + name_len > len(payload):
                print(f"    ⚠️  Truncated name at profile {i}")
                break

            name = payload[offset:offset+name_len].decode("utf-8", errors="replace")
            offset += name_len

            print(f"    Profile {i}: Index={idx} (1-based), Name='{name}'")

    elif opcode == OP_SET_RGB_KEY:
        print("  ➤ Set Single RGB Key")
        if len(payload) < 5:
            print("    ❌ Payload too short (expected 5 bytes)")
            return

        key_idx, r, g, b, w = struct.unpack("BBBBB", payload[:5])
        print(f"    Key Index: {key_idx}")
        print(f"    Color: R={r}, G={g}, B={b}, W={w} (brightness)")
        print(f"    Preview: rgb({r},{g},{b}) at {w}% brightness")

    elif opcode == OP_SET_ALL_RGB_KEYS:
        print("  ➤ Set All RGB Keys")
        if len(payload) < 64:
            print(f"    ❌ Payload too short (expected 64 bytes, got {len(payload)})")
            return

        print("    All 16 Key Colors (RGBW):")
        for i in range(16):
            idx = i * 4
            r, g, b, w = payload[idx:idx+4]
            print(f"      Key {i:2d}: R={r:3d}, G={g:3d}, B={b:3d}, W={w:3d}")

    elif opcode == OP_LOCK_DEVICE:
        print("  ➤ Lock/Unlock Device")
        if len(payload) < 1:
            print("    ❌ Payload too short")
            return

        lock_flag = payload[0]
        status = "LOCKED" if lock_flag == 1 else "UNLOCKED"
        print(f"    Lock Flag: 0x{lock_flag:02X} = {status}")

    elif opcode == OP_HELLO:
        print("  ➤ Hello (Protocol Handshake)")
        if len(payload) < 2:
            print("    ❌ Payload too short (need protocol_version + name_len)")
            return

        proto_ver = payload[0]
        name_len = payload[1]
        print(f"    Protocol Version: {proto_ver}")

        if len(payload) < 2 + name_len:
            print(f"    ❌ Payload too short for app version (need {name_len} bytes)")
            return

        app_ver = payload[2:2 + name_len].decode("utf-8", errors="replace")
        print(f"    App Version: '{app_ver}'")

        if proto_ver != PROTOCOL_VERSION:
            print(f"    ⚠️  Mismatch: decoder expects PROTOCOL_VERSION={PROTOCOL_VERSION}")

    elif opcode == OP_PROFILE_CHANGED:
        print("  ➤ Profile Changed (Device Event)")
        if len(payload) < 1:
            print("    ❌ Payload too short")
            return

        profile_idx = payload[0]
        print(f"    New Profile Index: {profile_idx} (0-based)")

    elif opcode == OP_BUTTON_PRESSED:
        print("  ➤ Button Pressed (Device Event)")
        if len(payload) < 2:
            print("    ❌ Payload too short")
            return

        profile_idx = payload[0]
        name_len = payload[1]

        if len(payload) < 2 + name_len:
            print("    ❌ Payload too short for button name")
            return

        button_name = payload[2:2+name_len].decode("utf-8", errors="replace")
        print(f"    Profile Index: {profile_idx} (0-based)")
        print(f"    Button Name: '{button_name}'")

    elif opcode == OP_KEY_PRESSED:
        print("  ➤ Key Pressed (Device Event)")
        if len(payload) < 2:
            print("    ❌ Payload too short")
            return

        profile_idx = payload[0]
        key_char = chr(payload[1])
        print(f"    Profile Index: {profile_idx} (0-based)")
        print(f"    Key Character: '{key_char}' (0x{payload[1]:02X})")

    elif opcode == OP_BATTERY_STATUS:
        print("  ➤ Battery Status (Device Event)")
        if len(payload) < 1:
            print("    ❌ Payload too short")
            return

        pct = payload[0]
        if pct == 0xFF:
            print("    Battery: 0xFF → no battery detected (USB-only power)")
        else:
            bar_filled = round(pct / 10)
            bar = "█" * bar_filled + "░" * (10 - bar_filled)
            print(f"    Battery: {pct}%")
            print(f"    Level  : [{bar}]")

    elif opcode == OP_DEVICE_TELEMETRY:
        print("  ➤ Device Telemetry (Device Event)")
        # Minimum = pv(1) + fvlen(1) + uptime(4) + reset(1) + heap(4) + ble_err(2) = 13 (empty fw version)
        if len(payload) < 2:
            print("    ❌ Payload too short (need protocol_version + fw_version_len)")
            return

        proto_ver = payload[0]
        fw_len = payload[1]
        offset = 2

        if len(payload) < offset + fw_len + 4 + 1 + 4 + 2:
            print(f"    ❌ Payload too short for declared fw_version_len={fw_len}")
            return

        fw_version = payload[offset:offset + fw_len].decode("utf-8", errors="replace")
        offset += fw_len

        uptime_ms = struct.unpack(">I", payload[offset:offset + 4])[0]
        offset += 4

        reset_reason = payload[offset]
        offset += 1

        free_heap = struct.unpack(">I", payload[offset:offset + 4])[0]
        offset += 4

        ble_error_count = struct.unpack(">H", payload[offset:offset + 2])[0]

        reset_label = RESET_REASON_NAMES.get(reset_reason, "OTHER")

        print(f"    Protocol Version: {proto_ver}")
        print(f"    Firmware Version: '{fw_version}'")
        print(f"    Uptime: {uptime_ms} ms ({uptime_ms / 1000:.1f} s)")
        print(f"    Reset Reason: {reset_reason} ({reset_label})")
        print(f"    Free Heap: {free_heap} bytes (~{free_heap // 1024} KB)")
        print(f"    BLE Error Count: {ble_error_count}")

        if proto_ver != PROTOCOL_VERSION:
            print(f"    ⚠️  Mismatch: decoder expects PROTOCOL_VERSION={PROTOCOL_VERSION}")

    else:
        print(f"  ⚠️  Unknown opcode 0x{opcode:02X}")
        if payload:
            print(f"    Raw payload: {payload.hex()}")


def create_test_packets():
    """Create and display test packets for all opcodes."""
    print("\n" + "=" * 80)
    print("TEST PACKET EXAMPLES")
    print("=" * 80)

    examples = [
        ("Keep Alive", "aa010000"),
        ("Keep Alive Reply", "aa810000"),
        ("Lock Device (locked)", "aa06000101"),
        ("Lock Device (unlocked)", "aa06000100"),
        ("Profile Changed (profile 0)", "aa82000100"),
        ("Profile Changed (profile 2)", "aa82000102"),
        ("Set RGB Key (key 5, red 50%)", "aa04000505ff000032"),
        ("Sync Profiles (Test, Default)", "aa03001002010454657374020744656661756c74"),
        ("Button Pressed (CON, profile 0)", "aa8300050003434f4e"),
        ("Key Pressed (key 'A', profile 0)", "aa840002" + "0041"),
        ("Battery Status (75%)", "aa850001" + "4b"),
        ("Battery Status (USB/none)", "aa850001" + "ff"),
        ("Hello (app v0.2.3, protocol v1)", "aa0700070105302e322e33"),
        ("Device Telemetry (fw v1.2.3, uptime 5s, POWERON)",
         "aa860012" + "0105312e322e33" + "00001388" + "01" + "00030d40" + "0000"),
    ]

    for name, hex_data in examples:
        print(f"\n{name}:")
        print(f"  Hex: {hex_data}")
        decode_packet(hex_data)


def main():
    """Main entry point."""
    print("BLE Protocol Decoder")
    print("=" * 80)

    if len(sys.argv) > 1:
        # Decode from command line
        hex_input = " ".join(sys.argv[1:])
        decode_packet(hex_input)
    else:
        # Interactive mode
        print("\nEnter hex string to decode (or 'test' for examples, 'quit' to exit):")

        while True:
            try:
                user_input = input("\n> ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ['quit', 'exit', 'q']:
                    break

                if user_input.lower() == 'test':
                    create_test_packets()
                    continue

                decode_packet(user_input)

            except (EOFError, KeyboardInterrupt):
                print("\n\nExiting...")
                break
            except Exception as e:
                print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
