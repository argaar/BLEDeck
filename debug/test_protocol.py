#!/usr/bin/env python3
"""
Test script to verify protocol encoding/decoding
"""

import ble_protocol
import struct

print("=" * 80)
print("BLE Protocol Encoding Test")
print("=" * 80)

# Test 1: Keep Alive
print("\n1. Keep Alive:")
packet = ble_protocol.keep_alive()
print(f"   Hex: {packet.hex()}")
print(f"   Expected: aa010000")
print(f"   Match: {'✓' if packet.hex() == 'aa010000' else '✗'}")

# Test 2: Lock Device
print("\n2. Lock Device (locked):")
packet = ble_protocol.lock_device(True)
print(f"   Hex: {packet.hex()}")
print(f"   Expected: aa060001 + 01")
print(f"   Breakdown:")
print(f"     START: {packet[0]:02x} (should be aa)")
print(f"     OPCODE: {packet[1]:02x} (should be 06)")
print(f"     LENGTH: {packet[2]:02x}{packet[3]:02x} (should be 0001)")
print(f"     PAYLOAD: {packet[4]:02x} (should be 01)")

# Test 3: Sync Profiles
print("\n3. Sync Profiles:")
profiles = {1: "Test", 3: "Default"}
packet = ble_protocol.sync_profiles(profiles)
print(f"   Hex: {packet.hex()}")
print(f"   Breakdown:")
print(f"     START: {packet[0]:02x}")
print(f"     OPCODE: {packet[1]:02x}")
print(f"     LENGTH: {(packet[2] << 8) | packet[3]:04x} = {(packet[2] << 8) | packet[3]} bytes")

offset = 4
count = packet[offset]
print(f"     COUNT: {count} profiles")
offset += 1

for i in range(count):
    idx = packet[offset]
    name_len = packet[offset + 1]
    offset += 2
    name = packet[offset:offset+name_len].decode("utf-8")
    offset += name_len
    print(f"       Profile {i+1}: index={idx}, name='{name}'")

# Test 4: Set RGB Key
print("\n4. Set RGB Key:")
packet = ble_protocol.set_rgb_key(0, 5, 255, 0, 0, 50)
print(f"   Hex: {packet.hex()}")
print(f"   Breakdown:")
print(f"     Profile Index: {packet[4]}")
print(f"     Key Index: {packet[5]}")
print(f"     R: {packet[6]}")
print(f"     G: {packet[7]}")
print(f"     B: {packet[8]}")
print(f"     W: {packet[9]}")

# Test 5: Set All RGB Keys
print("\n5. Set All RGB Keys:")
colors = [(255, 0, 0, 50)] * 16  # 16 red keys at 50% brightness
packet = ble_protocol.set_all_rgb_keys(colors)
print(f"   Hex: {packet.hex()}")
print(f"   Length: {len(packet)} bytes (should be 68: 4 header + 64 payload)")
print(f"   Payload size: {(packet[2] << 8) | packet[3]} bytes (should be 64)")

# Test 6: Parse incoming packets
print("\n6. Parse Test Packets:")

test_packets = [
    ("Keep Alive Reply", bytes.fromhex("aa810000")),
    ("Profile Changed to 0", bytes.fromhex("aa82000100")),
    ("Profile Changed to 2", bytes.fromhex("aa82000102")),
    ("Key Pressed 'A'", bytes.fromhex("aa84000200004141")),
]

for name, data in test_packets:
    print(f"\n   {name}:")
    print(f"   Hex: {data.hex()}")
    try:
        opcode, payload = ble_protocol.BLEPacket.parse(data)
        print(f"   Opcode: 0x{opcode:02x}")
        print(f"   Payload: {payload.hex() if payload else '(empty)'}")

        if opcode == ble_protocol.OP_PROFILE_CHANGED:
            idx = ble_protocol.parse_profile_changed(payload)
            print(f"   Decoded: Profile index = {idx}")
        elif opcode == ble_protocol.OP_KEY_PRESSED:
            prof_idx, key_char = ble_protocol.parse_key_pressed(payload)
            print(f"   Decoded: Profile={prof_idx}, Key='{key_char}'")
    except Exception as e:
        print(f"   ❌ Error: {e}")

print("\n" + "=" * 80)
print("Test complete!")
print("=" * 80)
