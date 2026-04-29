# BLEDeck Windows App

PyQt5 desktop application for the BLEDeck macro pad. Connects over BLE, manages profiles, assigns shell commands to keys, and syncs colors to the device.

---

## Requirements

- Windows 10 or 11
- Python 3.10 or later
- Bluetooth adapter with BLE support

---

## Setup

```bash
cd windows_app
pip install -r requirements.txt
python main.py
```

> A virtual environment is recommended:
> ```bash
> python -m venv env
> env\Scripts\activate
> pip install -r requirements.txt
> python main.py
> ```

---

## Usage

### Connecting

1. Power on the BLEDeck device.
2. Click **Connect** — the app scans for a device advertising as `BLEDeck` and connects automatically.
3. On connect the app: sends a keep-alive ping, syncs all profile names to the device, then pushes the current profile index and RGB key colors.
4. Enable **Auto-reconnect** to have the app reconnect automatically if the connection drops.

### Profiles

- Use the **Profile** dropdown to switch between profiles.
- Click **New Profile** to create an empty profile.
- Edit the name in the text field, then click **Save Profile**.
- Click **Delete Profile** to remove the current profile (at least one profile must remain).

Switching profiles in the app sends the new profile data to the device. Turning the encoder on the device also switches profiles and notifies the app.

### Keys

1. Click a key button in the 4×4 grid to select it.
2. Set a **Label** — shown on the button in the app.
3. Set a **Color** — enter `R,G,B,Brightness%` directly (e.g. `255,0,0,70`) or use **Pick Color** and the brightness slider. The LED on the device updates immediately.
4. Set a **Command** — any shell command or executable path (e.g. `notepad.exe`, `calc.exe`, `"C:\my app\tool.exe"`, `cmd /c echo hello`). Use **Browse** to pick an `.exe`.
5. Click **Save Profile** to persist the configuration.

When a key is pressed on the device, the app executes the configured command via `subprocess`.

### Battery

The battery percentage is shown in the top panel next to the connection status. It updates every ~30 seconds while connected. Shows `USB` when no battery is detected.

### Minimize to Tray

Closing or minimising the window hides it to the system tray. Double-click or single-click the tray icon to restore it. Right-click for **Open** / **Quit**.

---

## File Structure

| File | Purpose |
|------|---------|
| `main.py` | `BLEDeckGUI` — main window, BLE lifecycle, notification dispatch, command execution |
| `ble_protocol.py` | Packet builders, parsers, all opcode constants |
| `ble_client.py` | BleakClient re-export and BLE characteristic UUIDs |
| `profile_manager.py` | Load/save `profiles.json` |
| `profiles.json` | Auto-created on first run; stores all profiles and key configurations |
| `CLAUDE.md` | AI coding rules for this module |

---

## profiles.json

Profiles are stored in `profiles.json` in the working directory. Format:

```json
[
  {
    "name": "Default",
    "keys": {
      "0": { "label": "Notepad", "color": "100,150,255,70", "command": "notepad.exe" },
      "1": { "label": "Calc",    "color": "255,100,100,70", "command": "calc.exe" }
    }
  }
]
```

Keys with an empty `command` are not saved. Color format is `R,G,B,Brightness%` where brightness is `0–100`.

---

## BLE Protocol

The app communicates with the device using a custom binary protocol. See [`../docs/ble_protocol_reference.md`](../docs/ble_protocol_reference.md) for the full specification.

All packet construction and parsing is in `ble_protocol.py`. To decode a raw packet from the debug log:

```bash
cd ../debug
python protocol_decoder.py "aa 85 00 01 48"
```

### Handled incoming opcodes

| Opcode | Event | Action |
|--------|-------|--------|
| `0x81` | KEEP_ALIVE_REPLY | Logs pong, updates connection health timestamp |
| `0x82` | PROFILE_CHANGED | Syncs app profile to match device; sends new RGB colors back |
| `0x83` | BUTTON_PRESSED | Logs button name and profile index |
| `0x84` | KEY_PRESSED | Executes the configured command for that key and profile |
| `0x85` | BATTERY_STATUS | Updates battery label in the UI |

---

## Limitations

- **Windows only** — uses PyQt5 and bleak; no macOS or Linux support yet
- **Shell commands only** — keys execute shell commands; native keyboard injection is not implemented
- **Screen lock detection disabled** — the firmware supports a lock opcode but reliable detection from the app is not yet implemented
- **profiles.json saves to the working directory** — not the Windows `%APPDATA%` folder
- **10 profiles max, 16 keys per profile** — protocol limit
