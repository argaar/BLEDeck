# BLE Protocol Hex Quick Reference

This guide helps you decode hex packets directly from the logs without needing external tools.

## Packet Structure

```
AA | OP | LL LL | [PAYLOAD...]
│    │    │        └─ Variable data (0-n bytes)
│    │    └─ Length in bytes (big-endian, 2 bytes)
│    └─ Opcode (1 byte)
└─ Start byte (always 0xAA)
```

## Quick Opcode Reference

### Commands (App → Device)
- `01` - Keep Alive (PING)
- `02` - Change Profile
- `03` - Sync Profiles
- `04` - Set RGB Key (single)
- `05` - Set All RGB Keys
- `06` - Lock/Unlock Device
- `07` - Hello (protocol-version handshake)

### Events (Device → App)
- `81` - Keep Alive Reply (PONG)
- `82` - Profile Changed
- `83` - Button Pressed
- `84` - Key Pressed
- `85` - Battery Status
- `86` - Device Telemetry (reply to Hello)

## Reading Packets

### Example 1: Keep Alive
```
aa 01 00 00
│  │  │  └─ Length low byte: 0
│  │  └─ Length high byte: 0 (payload = 0 bytes)
│  └─ Opcode: 01 (Keep Alive)
└─ Start: AA ✓
```
**Meaning**: Ping to keep connection alive, no data.

### Example 2: Profile Changed
```
aa 82 00 01 02
│  │  │  │  └─ Payload: 02 = Profile index 2 (0-based)
│  │  │  └─ Length low: 01 (1 byte payload)
│  │  └─ Length high: 00
│  └─ Opcode: 82 (Profile Changed)
└─ Start: AA ✓
```
**Meaning**: Device switched to profile 2 (3rd profile, since 0-based).

### Example 3: Set RGB Key
```
aa 04 00 05 05 ff 00 00 32
│  │  │  │  │  │  │  │  └─ W: 50 (0x32 = 50 brightness)
│  │  │  │  │  │  │  └─ B: 0
│  │  │  │  │  │  └─ G: 0
│  │  │  │  │  └─ R: 255 (0xFF = 255)
│  │  │  │  └─ Key index: 5
│  │  │  └─ Length low: 05 (5 bytes)
│  │  └─ Length high: 00
│  └─ Opcode: 04 (Set RGB Key)
└─ Start: AA ✓
```
**Meaning**: Set key 5 to red (255,0,0) at 50% brightness.

### Example 4: Sync Profiles
```
aa 03 00 10 02 01 04 54 65 73 74 02 07 44 65 66 61 75 6c 74
│  │  │  │  │  │  │  └──┴──┴──┴──┘  │  └──┴──┴──┴──┴──┴──┴──┘
│  │  │  │  │  │  │  "Test" (UTF-8) │  "Default" (UTF-8)
│  │  │  │  │  │  └─ Name length: 4 └─ Name length: 7
│  │  │  │  │  └─ Profile 1 index: 1 (1-based)
│  │  │  │  │
│  │  │  │  │  (Profile 2 block starts at the second `02`: index=2, name_len=7)
│  │  │  │  └─ Count: 2 profiles
│  │  │  └─ Length: 16 bytes (0x0010)
│  └─ Opcode: 03 (Sync Profiles)
└─ Start: AA ✓
```
**Meaning**: Sync 2 profiles:
- Profile at index 1: "Test"
- Profile at index 2: "Default"

**Length math**: count(1) + idx(1)+nlen(1)+"Test"(4) + idx(1)+nlen(1)+"Default"(7) = 16 bytes → `0x0010`.

### Example 5: Key Pressed
```
aa 84 00 02 00 41
│  │  │  │  │  └─ Key: 0x41 = 'A' (ASCII)
│  │  │  │  └─ Profile: 0
│  │  │  └─ Length: 2 bytes
│  │  └─ Length high: 00
│  └─ Opcode: 84 (Key Pressed)
└─ Start: AA ✓
```
**Meaning**: Key 'A' was pressed while on profile 0.

### Example 6: Lock Device
```
aa 06 00 01 01
│  │  │  │  └─ Lock flag: 01 = LOCKED (00 = unlocked)
│  │  │  └─ Length: 1 byte
│  │  └─ Length high: 00
│  └─ Opcode: 06 (Lock Device)
└─ Start: AA ✓
```
**Meaning**: Lock the device (workstation locked).

### Example 7: Battery Status
```
aa 85 00 01 48
│  │  │  │  └─ Payload: 0x48 = 72 (72% battery)
│  │  │  └─ Length low: 01 (1 byte payload)
│  │  └─ Length high: 00
│  └─ Opcode: 85 (Battery Status)
└─ Start: AA ✓
```
**Meaning**: Device is at 72% battery.

```
aa 85 00 01 ff
```
**Meaning**: No battery detected - device is running on USB only (`0xFF` sentinel).

### Example 8: Set All RGB Keys
```
aa 05 00 40 ff 00 00 32 ff 00 00 32 ... (64 bytes total)
│  │  │  │  └──┴──┴──┴──┘ └──┴──┴──┴──┘
│  │  │  │  Key 0: R=255    Key 1: R=255
│  │  │  │         G=0             G=0
│  │  │  │         B=0             B=0
│  │  │  │         W=50            W=50
│  │  │  └─ Length: 64 bytes (0x0040) = 16 keys × 4 bytes
│  │  └─ Length high: 00
│  └─ Opcode: 05 (Set All RGB Keys)
└─ Start: AA ✓
```
**Meaning**: Set all 16 keys to red at 50% brightness.

### Example 9: Hello (Protocol Handshake)
```
aa 07 00 07 01 05 30 2e 32 2e 33
│  │  │  │  │  │  └──┴──┴──┴──┘
│  │  │  │  │  │  ASCII "0.2.3" (app version)
│  │  │  │  │  └─ App version length: 5
│  │  │  │  └─ Protocol version: 0x01 = 1 (PROTOCOL_VERSION constant)
│  │  │  └─ Length low: 07 (7 bytes)
│  │  └─ Length high: 00
│  └─ Opcode: 07 (Hello)
└─ Start: AA ✓
```
**Meaning**: Host (app v0.2.3) announces protocol version 1; firmware should reply with `0x86 DEVICE_TELEMETRY`.

**Length math**: protocol_version(1) + name_len(1) + "0.2.3"(5) = 7 → `0x0007`.

### Example 10: Device Telemetry
```
aa 86 00 12 01 05 31 2e 32 2e 33 00 00 13 88 01 00 03 0d 40 00 00
│  │  │  │  │  │  └──┴──┴──┴──┘  └──┴──┴──┴──┘ │  └──┴──┴──┴──┘ └──┴──┘
│  │  │  │  │  │  fw "1.2.3"     uptime BE u32 │  free_heap BE  ble_err
│  │  │  │  │  │                 = 0x00001388  │  = 0x00030D40  BE u16=0
│  │  │  │  │  │                 = 5000 ms     │  = 200000 B
│  │  │  │  │  │                               └─ reset_reason: 01 = POWERON
│  │  │  │  │  └─ Firmware version length: 5
│  │  │  │  └─ Protocol version: 1
│  │  │  └─ Length low: 12 (18 bytes)
│  │  └─ Length high: 00
│  └─ Opcode: 86 (Device Telemetry)
└─ Start: AA ✓
```
**Meaning**: Firmware v1.2.3 has been up 5 s since a power-on reset, has ~200 KB free heap, and has logged zero BLE errors.

**Big-endian breakdown**:
- `uptime_ms` = `00 00 13 88` = (0×2²⁴) + (0×2¹⁶) + (0x13×2⁸) + 0x88 = 4864 + 136 = **5000 ms**
- `free_heap` = `00 03 0d 40` = (0x03×2¹⁶) + (0x0D×2⁸) + 0x40 = 196608 + 3328 + 64 = **200000 bytes**
- `ble_error_count` = `00 00` = **0**

**Length math**: pv(1) + fvlen(1) + "1.2.3"(5) + uptime(4) + reset(1) + heap(4) + ble_err(2) = 18 → `0x0012`.

**Reset reason byte** (subset of `esp_reset_reason()`):
| Value | Meaning |
|-------|---------|
| `00` | Unknown |
| `01` | Power-on |
| `03` | Software reset |
| `05` | Deep-sleep wake |
| `06` | Brownout |
| `08` | Task watchdog |
| `09` | Interrupt watchdog |

## Decoding Tips

### Length Field
The length is 2 bytes, big-endian:
```
00 0e → 0x000E = 14 bytes
00 40 → 0x0040 = 64 bytes
01 00 → 0x0100 = 256 bytes
```

### ASCII to Character
Common key codes:
```
30-39 → '0'-'9'
41-46 → 'A'-'F'
```

### RGB Values
```
00 → 0 (off)
80 → 128 (half)
FF → 255 (full)
```

### Profile Indices
- **In commands**: 1-based (1, 2, 3, ...)
- **In events**: 0-based (0, 1, 2, ...)

## Common Patterns

### Connection Sequence
```
1. App → Device:  aa 01 00 00              [PING]
2. Device → App:  aa 81 00 00              [PONG]
3. App → Device:  aa 03 00 0e 02...        [SYNC profiles]
4. App → Device:  aa 05 00 40 ff...        [SET all RGB keys]
```

### Profile Switch (by device)
```
1. Device → App:  aa 82 00 01 02           [Profile changed to 2]
2. App → Device:  aa 05 00 40 ff...        [Send new RGB colors]
```

### Key Press
```
1. Device → App:  aa 84 00 02 00 41        [Key 'A' pressed]
2. App executes the command for key 'A'
```

## Debugging Checklist

When reading logs:

1. **First byte = AA?** ✓ Valid packet start
2. **Second byte** → Look up opcode above
3. **Bytes 3-4** → Calculate length (big-endian)
4. **Remaining bytes** → Should match length
5. **Profile indices**:
   - Commands use 1-based
   - Events use 0-based

## Example Log Analysis

**Log entry:**
```
📁 Synchronizing 2 profiles to device...
  Profile 1: 'Main'
  Profile 2: 'Gaming'
  Packet size: 19 bytes
→ aa03000f0201044d61696e0206 47616d696e67 [SYNC]
```

**Manual decode:**
```
aa            Start ✓
03            Sync Profiles
00 0f         Length = 15 bytes
02            Count = 2 profiles
  01          Profile index 1
  04          Name length 4
  4d 61 69 6e "Main" (hex to ASCII)
  02          Profile index 2
  06          Name length 6
  47 61 6d 69 6e 67  "Gaming"
```

**Verification:** body = count(1) + 1+1+4 + 1+1+6 = 15 bytes → `0x000F`. Full packet = 4-byte header + 15 = 19 bytes. ✓

---

**Pro Tip**: Use an online hex-to-ASCII converter for quick string decoding:
- `54657374` → "Test"
- `44656661756c74` → "Default"
