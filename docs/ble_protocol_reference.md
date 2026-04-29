# BLE Binary Protocol Reference

This document defines the binary communication protocol used between the Python host application and the Arduino-based peripheral device over BLE. It includes packet structure, opcodes, payload formats, and usage notes.

---

# 1. Overview
The protocol is designed to be compact, binary, and easy to parse on resource-limited devices. It uses a framed packet format with a fixed header and variable payload. Communication is unidirectional per opcode group:

- **0x01–0x7F** → Python **commands** sent to Arduino
- **0x80–0xFF** → Arduino **events** sent to Python

This version of the protocol uses **no acknowledgments**, as BLE handles transport-level reliability.

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
| `0x02` | Change Profile | Sends complete profile data (name + 16 RGBW keys) |
| `0x03` | Sync Profiles | Sends a dictionary of available profiles |
| `0x04` | Set RGB Key | Sets RGBW value for a single key |
| `0x05` | Set All RGB Keys | Sets RGBW values for all 16 keys at once |
| `0x06` | Lock / Unlock Device | Locks or unlocks device functionality |

## 3.2 Arduino → Python (Events)
| Opcode | Name | Description |
|--------|------|-------------|
| `0x81` | Keep Alive Reply | Arduino's response to keep-alive ping |
| `0x82` | Profile Changed | Arduino notifies that the user switched profile |
| `0x83` | Button Pressed | Arduino notifies that a button was pressed |
| `0x84` | Key Pressed | Arduino notifies that a keypad key was pressed |
| `0x85` | Battery Status | Arduino reports current battery level (sent after each ADC reading, ~every 30 s) |

*(No lock event exists; locking is one-way as requested.)*

---

# 4. Payload Formats
This section defines the payload layout for each opcode.

## 4.1 Keep Alive — `0x01`
**Payload:** none

Packet:
```
AA 01 00 00
```

### 4.1.1 Keep Alive Reply — `0x81`
**Payload:** none

Packet:
```
AA 81 00 00
```

---

## 4.2 Change Profile — `0x02`
Sends complete profile data including name and 16 RGBW values.

### Payload Structure
```
+------------------+
| profile_index 1B |
| name_length   1B |
| name       ...   |
| key0 R G B W     |
| key1 R G B W     |
| ...              |
| key15 R G B W    |
+------------------+
```

- `profile_index` — integer 1..255
- `name_length` — length of profile name in bytes
- `name` — UTF-8 encoded string
- `keys` — 16 × RGBW values (each 4 bytes)

Each RGBW:
```
R(1B), G(1B), B(1B), W(1B)
```

---

## 4.3 Sync Profiles — `0x03`
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

- `count` — number of profile entries
- For each entry:
  - `index` — profile index
  - `name_len` — name length
  - `name` — profile name (UTF-8)

---

## 4.4 Set RGB Key — `0x04`
Sets the RGBW value for a single key.

### Payload Structure
```
+--------------------+
| key_index     1B   |
| R 1B | G 1B | B 1B |
| W 1B                |
+--------------------+
```

- `key_index` — which key (0–15)
- `R,G,B,W` — color values (0–255)

---

## 4.5 Set All RGB Keys — `0x05`
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

## 4.6 Lock Device — `0x06`
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

## 4.7 Profile Changed (Arduino → Python) — `0x82`
Sent when the user switches profile on the device.

### Payload Structure
```
+------------------+
| new_profile  1B  |
+------------------+
```

---

## 4.8 Button Pressed (Arduino → Python) — `0x83`
Sent when a button (CON, BACK, PUSH) is pressed on the device.

### Payload Structure
```
+------------------+
| profile_index 1B |
| name_length   1B |
| button_name  ... |
+------------------+
```

- `profile_index` — current active profile index
- `name_length` — length of button name
- `button_name` — button identifier string (e.g., "CON", "BACK", "PUSH")

---

## 4.9 Key Pressed (Arduino → Python) — `0x84`
Sent when a keypad key (0-9, A-F) is pressed on the device.

### Payload Structure
```
+------------------+
| profile_index 1B |
| key           1B |
+------------------+
```

- `profile_index` — current active profile index
- `key` — ASCII value of the key pressed (0-9, A-F)

---

## 4.10 Battery Status (Arduino → Python) — `0x85`
Sent automatically after each ADC battery reading (~every 30 s) while a host is connected.

### Payload Structure
```
+-----------+
| percent 1B|
+-----------+
```

- `percent` — battery level `0–100` (integer percentage), or `0xFF` (255) when no battery is detected (e.g. device running on USB without a LiPo cell)

Example (72 % battery):
```
AA 85 00 01  48
```

Example (USB / no battery):
```
AA 85 00 01  FF
```

---

# 5. Encoding Notes
- All numbers are unsigned.
- All multi-byte values are big-endian.
- Strings use UTF-8 encoding.
- BLE characteristics should be configured for **binary** (not hex or text) transfer.
- No checksums are required since BLE guarantees delivery and integrity.

---

# 6. Design Conventions
- Opcodes below `0x80` are **commands**.
- Opcodes above `0x80` are **events**.
- `0xAA` is used as a constant start byte for easy packet framing.
- Variable-length strings always use `[length][data...]` format.
- The protocol is designed to be extensible for new features.

---

# 7. Versioning
This document describes **Protocol Version 1.0**.
If future changes are introduced, a new opcode (`0x7F`) may be added for version negotiation.

---

# 8. License
This specification may be shared and published publicly.

