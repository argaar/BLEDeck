# BLE Protocol Debugging Guide

This guide explains how to debug the binary protocol communication between the Windows app and the Arduino firmware.

## Overview

The protocol uses binary packets with the following structure:
```
[START_BYTE][OPCODE][LENGTH_H][LENGTH_L][PAYLOAD...]
```

- **START_BYTE**: Always `0xAA`
- **OPCODE**: Command/Event identifier (1 byte)
- **LENGTH**: Payload length in bytes, big-endian (2 bytes)
- **PAYLOAD**: Variable-length data (0-255 bytes)

## Using the Protocol Decoder

The `protocol_decoder.py` script can decode hex strings and explain all operations.

### Command Line Usage

```bash
# Decode a single packet
python protocol_decoder.py aa010000

# Decode with spaces
python protocol_decoder.py "aa 01 00 00"

# Show test examples
python protocol_decoder.py test
```

### Interactive Mode

```bash
python protocol_decoder.py

# Then enter hex strings at the prompt
> aa010000
> aa82000102
> test
> quit
```

## Common Packets

### Commands (App → Device)

#### Keep Alive (0x01)
```
aa 01 00 00
```
- No payload
- Sent periodically to maintain connection

#### Sync Profiles (0x03)
```
aa 03 00 0e 02 01 04 54657374 03 07 44656661756c74
```
- Byte 4: Count (0x02 = 2 profiles)
- For each profile:
  - Profile index (1-based)
  - Name length
  - Name bytes (UTF-8)

Example breakdown:
- `02` - 2 profiles
- `01 04 54657374` - Profile 1: length=4, name="Test"
- `03 07 44656661756c74` - Profile 3: length=7, name="Default"

#### Set RGB Key (0x04)
```
aa 04 00 06 00 05 ff 00 00 32
```
- Byte 4: Profile index
- Byte 5: Key index (0-15)
- Byte 6-9: R, G, B, W values

#### Set All RGB Keys (0x05)
```
aa 05 00 40 [64 bytes of RGBW data]
```
- 16 keys × 4 bytes = 64 bytes total
- Each key: R, G, B, W (1 byte each)

#### Lock Device (0x06)
```
aa 06 00 01 01    (locked)
aa 06 00 01 00    (unlocked)
```

### Events (Device → App)

#### Keep Alive Reply (0x81)
```
aa 81 00 00
```

#### Profile Changed (0x82)
```
aa 82 00 01 02
```
- Byte 4: New profile index (0-based)

#### Button Pressed (0x83)
```
aa 83 00 04 00 03 43 4f 4e
```
- Byte 4: Profile index (0-based)
- Byte 5: Button name length
- Bytes 6+: Button name ("CON")

#### Key Pressed (0x84)
```
aa 84 00 02 00 41
```
- Byte 4: Profile index (0-based)
- Byte 5: Key character ASCII (0x41 = 'A')

## Debugging in the Windows App

The Windows app logs all packets in hex format:

### Outgoing Packets
Look for lines like:
```
→ aa03000e020104...
```
This is the hex data being sent to the device.

### Incoming Packets
Look for lines like:
```
← aa82000102
```
This is the hex data received from the device.

### Decode a Log Entry

1. Copy the hex string from the log
2. Run the decoder:
   ```bash
   python protocol_decoder.py aa82000102
   ```

3. Output:
   ```
   PACKET ANALYSIS
   ================
   Raw hex: aa82000102
   Length: 5 bytes

   HEADER:
     Start Byte: 0xAA ✓
     Opcode:     0x82 - PROFILE_CHANGED
     Length:     1 bytes (0x0001)

   PAYLOAD (1 bytes):
     Hex: 02
     Bytes: 02

   DECODED PAYLOAD:
     ➤ Profile Changed (Device Event)
       New Profile Index: 2 (0-based)
   ```

## Common Issues

### Profile Sync Not Working

**Symptom**: Device doesn't show correct profile names

**Debug**:
1. Look for the sync packet in the log: `→ aa03...`
2. Decode it with the decoder
3. Verify:
   - Count matches number of profiles
   - Each profile has correct index (1-based)
   - Names are correctly encoded

**Expected packet for 2 profiles**:
```
aa 03 00 0e 02 01 07 50726f66696c65 02 09 50726f66696c6532
         │  │  │  │                │  │  │
         │  │  │  └─ "Profile"     │  │  └─ "Profile2"
         │  │  └─ length=7         │  └─ length=9
         │  └─ index=1             └─ index=2
         └─ count=2
```

### RGB Colors Not Updating

**Symptom**: LEDs don't change color

**Debug**:
1. Check for RGB packet: `→ aa05...` (all keys) or `→ aa04...` (single key)
2. Decode to verify colors
3. For Set All RGB Keys:
   - Packet should be exactly 68 bytes (4 header + 64 payload)
   - Each key should have 4 bytes (RGBW)

### Profile Changes Not Detected

**Symptom**: App doesn't sync when device profile changes

**Debug**:
1. Look for incoming packets: `← aa82...`
2. Decode to see the profile index
3. Verify the index is 0-based (0, 1, 2, not 1, 2, 3)
4. Check if profile index is within app's profile range

## Testing Protocol Encoding

Use the `test_protocol.py` script to verify encoding:

```bash
python test_protocol.py
```

This will:
- Encode test packets
- Display hex output
- Parse them back
- Verify correctness

## Manual Packet Creation

You can manually create packets for testing:

```python
import ble_protocol

# Create a keep-alive packet
packet = ble_protocol.keep_alive()
print(packet.hex())  # aa010000

# Create a sync profiles packet
profiles = {1: "Test", 2: "Default"}
packet = ble_protocol.sync_profiles(profiles)
print(packet.hex())

# Parse an incoming packet
data = bytes.fromhex("aa82000102")
opcode, payload = ble_protocol.BLEPacket.parse(data)
profile_idx = ble_protocol.parse_profile_changed(payload)
print(f"Profile changed to: {profile_idx}")
```

## Arduino Serial Debug Output

The Arduino firmware logs protocol operations to Serial:

```
RX <- Opcode: 0x03, Length: 14
Syncing 2 profiles
Synced profile 1: 'Test'
Synced profile 2: 'Default'
```

Match these with the app logs to verify communication.

## Troubleshooting Checklist

- [ ] START_BYTE is always 0xAA
- [ ] Opcode matches expected command/event
- [ ] LENGTH field matches actual payload size
- [ ] Profile indices are 1-based in commands, 0-based in events
- [ ] Strings are UTF-8 encoded with length prefix
- [ ] RGB values are in range 0-255
- [ ] All multi-byte values are big-endian
- [ ] Packet fits within BLE MTU (typically 512 bytes)

## Example Debugging Session

**Problem**: Profiles not syncing to device

**Step 1**: Check app log for sync packet
```
📁 Synchronizing 2 profiles to device...
  Profile 1: 'My Profile'
  Profile 2: 'Gaming'
  Packet size: 32 bytes
→ aa03001c020109...
```

**Step 2**: Decode the packet
```bash
python protocol_decoder.py aa03001c020109...
```

**Step 3**: Verify output
- Count = 2 ✓
- Profile 1: index=1, name="My Profile" ✓
- Profile 2: index=2, name="Gaming" ✓

**Step 4**: Check Arduino serial output
```
RX <- Opcode: 0x03, Length: 28
Syncing 2 profiles
Synced profile 1: 'My Profile'
Synced profile 2: 'Gaming'
```

✓ **Resolution**: Protocol is working correctly, profiles synced successfully.
