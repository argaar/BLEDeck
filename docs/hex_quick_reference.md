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

### Events (Device → App)
- `81` - Keep Alive Reply (PONG)
- `82` - Profile Changed
- `83` - Button Pressed
- `84` - Key Pressed
- `85` - Battery Status

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
aa 04 00 06 05 ff 00 00 32
│  │  │  │  │  │  │  │  └─ W: 50 (0x32 = 50 brightness)
│  │  │  │  │  │  │  └─ B: 0
│  │  │  │  │  │  └─ G: 0
│  │  │  │  │  └─ R: 255 (0xFF = 255)
│  │  │  │  └─ Key index: 5
│  │  │  └─ Length low: 06 (6 bytes)
│  │  └─ Length high: 00
│  └─ Opcode: 04 (Set RGB Key)
└─ Start: AA ✓
```
**Meaning**: Set key 5 to red (255,0,0) at 50% brightness.

### Example 4: Sync Profiles
```
aa 03 00 0e 02 01 04 54 65 73 74 03 07 44 65 66 61 75 6c 74
│  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  └┐
│  │  │  │  │  │  │  └──┴──┴──┴──┘  │  └──┴──┴──┴──┴──┴──┴──┘ │
│  │  │  │  │  │  │  "Test" (UTF-8)  │  "Default" (UTF-8)     │
│  │  │  │  │  │  └─ Name length: 4  └─ Name length: 7        │
│  │  │  │  │  └─ Profile index: 1 (1-based)                  │
│  │  │  │  └─ Count: 2 profiles                              │
│  │  │  └─ Length: 14 bytes (0x000E)                         │
│  └─ Opcode: 03 (Sync Profiles)                              │
└─ Start: AA ✓                                                │
                                                              │
Profile 2: Index=3, Length=7, Name="Default" ─────────────────┘
```
**Meaning**: Sync 2 profiles:
- Profile at index 1: "Test"
- Profile at index 3: "Default"

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
  Packet size: 23 bytes
→ aa03001302010446614d696e02064761616d696e67 [SYNC]
```

**Manual decode:**
```
aa          Start ✓
03          Sync Profiles
00 13       Length = 19 bytes
02          Count = 2 profiles
  01        Profile index 1
  04        Name length 4
  4d616966  "Main" (hex to ASCII)
  02        Profile index 2
  06        Name length 6
  47616d696e67  "Gaming"
```

**Verification:** ✓ Packet is correctly formatted, sending 2 profiles.

---

**Pro Tip**: Use an online hex-to-ASCII converter for quick string decoding:
- `54657374` → "Test"
- `44656661756c74` → "Default"
