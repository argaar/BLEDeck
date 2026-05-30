# BLE Binary Protocol Reference

This document defines the binary communication protocol used between the Python host application and the Arduino-based peripheral device over BLE. It includes packet structure, opcodes, payload formats, and usage notes.

---

# 1. Overview
The protocol is designed to be compact, binary, and easy to parse on resource-limited devices. It uses a framed packet format with a fixed header and variable payload. Communication is unidirectional per opcode group:

- **0x01–0x7F** → Python **commands** sent to Arduino
- **0x80–0xFF** → Arduino **events** sent to Python

This version of the protocol uses **no acknowledgments**, as BLE handles transport-level reliability.

## 1.1 Pairing & Encryption

Both GATT characteristics require an encrypted, MITM-authenticated link:

- TX (notify) — `ESP_GATT_PERM_READ_ENC_MITM`
- RX (write)  — `ESP_GATT_PERM_WRITE_ENC_MITM`

Pairing flow on first connect:

1. Host (Windows app) initiates pairing through the OS BLE stack.
2. Device displays a 6-digit passkey on its OLED.
3. User types the passkey into the OS pairing prompt.
4. Bond is stored in NVS and reused on subsequent connects.

Without an active bond, GATT writes are rejected by the controller before the application layer sees them. This blocks unauthenticated centrals from sending `LOCK_DEVICE`, `CHANGE_PROFILE`, or RGB commands.

## 1.2 Transport

| Item | Value |
|------|-------|
| Device name | `BLEDeck` |
| Service UUID | `4FAFC201-1FB5-459E-8FCC-C5C9C331914B` |
| TX characteristic (Device → PC, NOTIFY) | `BEB5483E-36E1-4688-B7F5-EA07361B26A8` |
| RX characteristic (PC → Device, WRITE)  | `EAB5483E-36E1-4688-B7F5-EA07361B26A9` |

TX uses notify (device pushes events). RX uses write-without-response (PC pushes commands).

---

# 2. Packet Structure
All packets follow this structure:

```
+-----------+-----------+--------------+------------------+
| START(1B) | OPCODE(1B)| LENGTH(2B)   | PAYLOAD (0..n B) |
+-----------+-----------+--------------+------------------+
```

| Field  | Size | Description |
|--------|------|-------------|
| **START** | 1 byte | Always `0xAA` (frame sync marker) |
| **OPCODE** | 1 byte | Operation identifier |
| **LENGTH** | 2 bytes | Payload length in bytes, big-endian |
| **PAYLOAD** | variable | Operation-specific data |

---

# 3. Opcodes

## 3.1 Python → Arduino (Commands)
| Opcode | Name | Description |
|--------|------|-------------|
| `0x01` | Keep Alive | Ping packet used to keep BLE connection active |
| `0x02` | Change Profile | Notifies device of active profile (index + name) |
| `0x03` | Sync Profiles | Sends a dictionary of available profiles |
| `0x04` | Set RGB Key | Sets RGBW value for a single key |
| `0x05` | Set All RGB Keys | Sets RGBW values for all 16 keys at once |
| `0x06` | Lock / Unlock Device | Locks or unlocks device functionality |
| `0x07` | Hello | Protocol-version handshake sent immediately after notify subscription |

## 3.2 Arduino → Python (Events)
| Opcode | Name | Description |
|--------|------|-------------|
| `0x81` | Keep Alive Reply | Arduino's response to keep-alive ping |
| `0x82` | Profile Changed | Arduino notifies that the user switched profile |
| `0x83` | Button Pressed | Arduino notifies that a button was pressed |
| `0x84` | Key Pressed | Arduino notifies that a keypad key was pressed |
| `0x85` | Battery Status | Arduino reports current battery level (sent after each ADC reading, ~every 30 s) |
| `0x86` | Device Telemetry | Arduino replies to `HELLO` with firmware/protocol version + runtime stats |

*(No lock event exists; locking is one-way as requested.)*

---

# 4. Payload Formats
This section defines the payload layout for each opcode.

## 4.1 Keep Alive - `0x01`
**Payload:** none

Packet:
```
AA 01 00 00
```

---

## 4.2 Change Profile - `0x02`
Notifies the device that the active profile has changed and provides its display name.

### Payload Structure
```
+------------------+
| profile_index 1B |
| name_length   1B |
| name       ...   |
+------------------+
```

- `profile_index` - integer 1..255
- `name_length` - length of profile name in bytes
- `name` - UTF-8 encoded string

> RGB colors are pushed separately via `SET_ALL_RGB_KEYS` (0x05) following the
> profile switch — that is the actual connection bootstrap sequence.

---

## 4.3 Sync Profiles - `0x03`
Sends a dictionary of `index → name` entries.

### Payload Structure
```
+------------------+
| count        1B  |
| index0       1B  |
| name0_len    1B  |
| name0        ... |
| index1       1B  |
| name1_len    1B  |
| name1        ... |
| ...              |
+------------------+
```

- `count` - number of profile entries
- For each entry:
  - `index` - profile index
  - `name_len` - name length
  - `name` - profile name (UTF-8)

---

## 4.4 Set RGB Key - `0x04`
Sets the RGBW value for a single key.

### Payload Structure
```
+--------------------+
| key_index     1B   |
| R 1B | G 1B | B 1B |
| W 1B                |
+--------------------+
```

- `key_index` - which key (0–15)
- `R,G,B,W` - color values (0–255)

---

## 4.5 Set All RGB Keys - `0x05`
Sets RGBW values for all 16 keys at once. This is typically sent when switching profiles to update all LEDs simultaneously.

### Payload Structure
```
+--------------------+
| key0  R G B W      |
| key1  R G B W      |
| key2  R G B W      |
| ...                |
| key15 R G B W      |
+--------------------+
```

- 16 × RGBW values (64 bytes total)
- Each RGBW: R(1B), G(1B), B(1B), W(1B)
- Keys are in order from 0 to 15

---

## 4.6 Lock Device - `0x06`
Locks or unlocks device functionality.

### Payload Structure
```
+----------------+
| lock_flag  1B  |
+----------------+
```

- `0x01` = lock
- `0x00` = unlock

No event/acknowledgment is generated.

Example (lock):
```
AA 06 00 01  01
```

---

## 4.7 Hello - `0x07`
Protocol-version handshake. Sent by the host immediately after it finishes subscribing to the TX notify characteristic, **before** any other command is issued.

### Payload Structure
```
+----------------------+
| protocol_version 1B  |
| app_version_len  1B  |
| app_version      ... |
+----------------------+
```

- `protocol_version` - currently `0x01` (see `PROTOCOL_VERSION` constant in `windows_app/ble_protocol.py` and `firmware/src/protocolparser.h`)
- `app_version_len` - length of the host application version string (bytes)
- `app_version` - UTF-8 encoded semver string, e.g. `"0.2.3"`

### Behaviour
Upon receipt the firmware replies with `OP_DEVICE_TELEMETRY` (`0x86`) carrying its own protocol version, firmware version, and runtime stats. The host compares `protocol_version` values: a mismatch surfaces a **CRITICAL** entry in the debug log and a warning in the status bar, then continues at the host's risk.

### Mismatch handling
`PROTOCOL_VERSION` is bumped on **any breaking change** to packet framing or payload layout. Additive changes (new opcode, additional trailing field) do **not** bump the version. Both sides must stay in lockstep — if you change one, change the other.

Example (host v0.2.3, protocol_version=1):
```
AA 07 00 07  01 05 30 2E 32 2E 33
```

---

# 5. Device → Python Events

## 5.1 Keep Alive Reply - `0x81`
**Payload:** none

Packet:
```
AA 81 00 00
```

---

## 5.2 Profile Changed - `0x82`
Sent when the user switches profile on the device.

### Payload Structure
```
+------------------+
| new_profile  1B  |
+------------------+
```

---

## 5.3 Button Pressed - `0x83`
Sent when a button (CON, BACK, PUSH) is pressed on the device.

### Payload Structure
```
+------------------+
| profile_index 1B |
| name_length   1B |
| button_name  ... |
+------------------+
```

- `profile_index` - current active profile index
- `name_length` - length of button name
- `button_name` - button identifier string (e.g., "CON", "BACK", "PUSH")

---

## 5.4 Key Pressed - `0x84`
Sent when a keypad key (0-9, A-F) is pressed on the device.

### Payload Structure
```
+------------------+
| profile_index 1B |
| key           1B |
+------------------+
```

- `profile_index` - current active profile index
- `key` - ASCII value of the key pressed (0-9, A-F)

---

## 5.5 Battery Status - `0x85`
Sent automatically after each ADC battery reading (~every 30 s) while a host is connected.

### Payload Structure
```
+-----------+
| percent 1B|
+-----------+
```

- `percent` - battery level `0–100` (integer percentage), or `0xFF` (255) when no battery is detected (e.g. device running on USB without a LiPo cell)

Example (72 % battery):
```
AA 85 00 01  48
```

Example (USB / no battery):
```
AA 85 00 01  FF
```

---

## 5.6 Device Telemetry - `0x86`
Reply to `OP_HELLO` (`0x07`). Carries the firmware's protocol version, firmware version string, and runtime statistics. Sent once per handshake; not periodic.

### Payload Structure
```
+------------------------+
| protocol_version    1B |
| fw_version_len      1B |
| firmware_version   ... |
| uptime_ms           4B |   (big-endian uint32)
| reset_reason        1B |
| free_heap           4B |   (big-endian uint32)
| ble_error_count     2B |   (big-endian uint16)
+------------------------+
```

### Fields

- `protocol_version` - device-side `PROTOCOL_VERSION` constant; compared against the host's value from `OP_HELLO`. Mismatch ⇒ host logs a CRITICAL warning.
- `fw_version_len` - length of `firmware_version` in bytes.
- `firmware_version` - UTF-8 semver string (e.g. `"1.2.3"`), from `firmware/src/version.h`.
- `uptime_ms` - milliseconds since boot, big-endian uint32. Wraps at ~49.7 days.
- `reset_reason` - byte mirroring `esp_reset_reason()`:
  - `0` = unknown
  - `1` = power-on
  - `3` = software reset
  - `5` = deep-sleep wake
  - `6` = brownout
  - `8` = task watchdog
  - `9` = interrupt watchdog
  - (full set: ESP-IDF `esp_reset_reason_t` docs)
- `free_heap` - free heap in bytes at the moment of telemetry, big-endian uint32.
- `ble_error_count` - count of malformed packets, send failures, and oversize-payload rejections since boot, big-endian uint16. A sudden spike points to radio interference or app/firmware-version drift — investigate before suspecting other layers.

Example (fw `1.2.3`, uptime 5000 ms, reset_reason=1 power-on, free_heap=200000, ble_error_count=0):
```
AA 86 00 12  01 05 31 2E 32 2E 33  00 00 13 88  01  00 03 0D 40  00 00
```

---

# 6. Encoding Notes
- All numbers are unsigned.
- All multi-byte values are big-endian.
- Strings use UTF-8 encoding.
- BLE characteristics should be configured for **binary** (not hex or text) transfer.
- No checksums are required since BLE guarantees delivery and integrity. Application-layer recovery relies on the `0xAA` start byte; the parser silently discards any bytes received outside a valid frame.
- `PROTOCOL_VERSION` (currently `1`) is the single-byte version constant exchanged in `OP_HELLO` / `OP_DEVICE_TELEMETRY`. **Bump policy:** increment on any breaking change to packet framing or payload layout. Additive changes (new opcode, new trailing field on an existing opcode) do **not** bump the version. The constant is defined in both `windows_app/ble_protocol.py` and `firmware/src/protocolparser.h` — keep them in lockstep.

---

# 7. Design Conventions
- Opcodes below `0x80` are **commands**.
- Opcodes above `0x80` are **events**.
- `0xAA` is used as a constant start byte for easy packet framing.
- Variable-length strings always use `[length][data...]` format.
- The protocol is designed to be extensible for new features.

---

# 8. Versioning
This document describes **Protocol Version 1** (`PROTOCOL_VERSION = 1`). Version negotiation is implemented via `OP_HELLO` (`0x07`) → `OP_DEVICE_TELEMETRY` (`0x86`); see §4.7 and §5.6. See §6 for bump policy.

---

# 9. License
This specification may be shared and published publicly.

