#!/usr/bin/env python3
"""
BLE Protocol Decoder and Analyzer
This script decodes binary packets from the BLEDeck protocol and explains all operations.
"""

import struct
import sys

# Protocol constants
START_BYTE = 0xAA

# Opcodes - Commands (Python → Arduino)
OP_KEEP_ALIVE        = 0x01
OP_CHANGE_PROFILE    = 0x02
OP_SYNC_PROFILES     = 0x03
OP_SET_RGB_KEY       = 0x04
OP_SET_ALL_RGB_KEYS  = 0x05
OP_LOCK_DEVICE       = 0x06

# Opcodes - Events (Arduino → Python)
OP_KEEP_ALIVE_REPLY  = 0x81
OP_PROFILE_CHANGED   = 0x82
OP_BUTTON_PRESSED    = 0x83
OP_KEY_PRESSED       = 0x84

OPCODE_NAMES = {
    0x01: "KEEP_ALIVE",
    0x02: "CHANGE_PROFILE",
    0x03: "SYNC_PROFILES",
    0x04: "SET_RGB_KEY",
    0x05: "SET_ALL_RGB_KEYS",
    0x06: "LOCK_DEVICE",
    0x81: "KEEP_ALIVE_REPLY",
    0x82: "PROFILE_CHANGED",
    0x83: "BUTTON_PRESSED",
    0x84: "KEY_PRESSED",
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
        print(f"    Profile Index: {profile_idx} (device uses 1-based, converts to {profile_idx-1} internally)")
        print(f"    Name Length: {name_len} bytes")

        if len(payload) < 2 + name_len:
            print("    ❌ Payload too short for name")
            return

        name = payload[2:2+name_len].decode("utf-8", errors="replace")
        print(f"    Profile Name: '{name}'")

        # RGB colors
        offset = 2 + name_len
        colors_data = payload[offset:]
        expected_colors = 64  # 16 keys × 4 bytes

        print(f"    RGB Colors: {len(colors_data)} bytes (expected {expected_colors})")
        if len(colors_data) >= expected_colors:
            print("    Key Colors (RGBW):")
            for i in range(16):
                idx = i * 4
                r, g, b, w = colors_data[idx:idx+4]
                print(f"      Key {i:2d}: R={r:3d}, G={g:3d}, B={b:3d}, W={w:3d}")
        else:
            print("    ⚠️  Insufficient color data")

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
        ("Lock Device (locked)", "aa0600010001"),
        ("Lock Device (unlocked)", "aa0600010000"),
        ("Profile Changed (profile 0)", "aa8200010100"),
        ("Profile Changed (profile 2)", "aa8200010102"),
        ("Set RGB Key (profile 0, key 5, red)", "aa040006000005ff000000"),
        ("Sync Profiles (2 profiles)", "aa030009020154657374031044656661756c74"),
        ("Button Pressed (CON)", "aa83000400030343434e"),
        ("Key Pressed (key 'A')", "aa840002000141"),
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

            except KeyboardInterrupt:
                print("\n\nExiting...")
                break
            except Exception as e:
                print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
