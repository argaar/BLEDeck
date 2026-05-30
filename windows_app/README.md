# BLEDeck Windows App

PyQt5 desktop application for the BLEDeck macro pad.
Connects over BLE, manages profiles, assigns shell commands or recorded macros to keys, and syncs colors to the device.

---

## Features

- **Rotating debug log** at `%APPDATA%\BLEDeck\logs\bledeck.log` — 5 × 20 MB rotation (100 MB cap); KEEP_ALIVE traffic filtered out; opens cleanly in any text editor
- **Preferred device MAC pinning** — first MAC connected is persisted in `%APPDATA%\BLEDeck\app_settings.json` and preferred on every scan thereafter; supports multi-BLEDeck environments
- **Exponential reconnect backoff** — auto-reconnect starts at 10 s and doubles per failed attempt up to a 5 min cap; resets to 10 s on the first successful connect
- **Workstation-lock subscription** — uses `WTSRegisterSessionNotification` for sub-50 ms lock detection on physical Windows; falls back to a 2.5 s poll on virtualized desktops
- **High-risk command warning** — profile-file load surfaces a `QMessageBox.warning` listing any commands containing tokens such as `powershell`, `cmd /c`, `iex`, `curl … | iex`, `bitsadmin`, `mshta` — review before pressing the matching device key
- **Macro recorder auto-stop** — recording sessions auto-terminate after 60 s of idle keyboard / mouse activity to limit accidental capture
- **Protocol handshake** — sends `OP_HELLO` on connect; logs `OP_DEVICE_TELEMETRY` reply (firmware version, uptime, free heap, BLE error count); CRITICAL warning if `PROTOCOL_VERSION` mismatches

---

## Requirements

- Windows 10 or 11
- Python 3.12 or later
- Bluetooth adapter with BLE support

> **Windows only.** This app links against Win32 APIs through `ctypes` (workstation-lock detection, multi-monitor enumeration) and PyQt5 system tray integration that targets the Windows shell. macOS and Linux are not supported and `build.bat` will not run on those platforms.

---

## Setup

```bash
cd windows_app
pip install -r requirements.txt        # runtime
pip install -r requirements-dev.txt    # tests (optional)
python main.py
```

> A virtual environment is recommended:
> ```bash
> python -m venv env
> env\Scripts\activate
> pip install -r requirements.txt
> python main.py
> ```

> For development (running the test suite), use `setup-dev.bat` from an activated venv — it installs both `requirements.txt` and `requirements-dev.txt`, then runs `pytest` to verify the environment.

### Running Tests

Install dev dependencies first (`pytest` lives in `requirements-dev.txt`, not `requirements.txt`):

```bash
pip install -r requirements-dev.txt
python -m pytest tests/
```

---

## Development Without Hardware

A software simulator is available in [`simulator/`](../simulator/README.md). It emulates the BLEDeck device so the app can be developed and tested without a physical device.

**Quick start — loopback mode (no Bluetooth needed):**

```bash
set BLEDECK_SIM=1
python main.py
```

The app connects instantly to a fake in-process device. A `sim>` CLI prompt appears in the terminal — use it to trigger button presses, battery updates, and profile changes.

**Real BLE mode** (requires two machines — Windows does not support BLE self-connection):

```bash
# Machine A — start the simulator
python -m simulator --ble

# Machine B — run the app normally
python windows_app/main.py
```

See [`simulator/README.md`](../simulator/README.md) for full details and CLI command reference.

---

## Building a Standalone Executable

`build.bat` is a Windows batch script and only runs on Windows. There is no macOS / Linux equivalent.

Produces a self-contained `dist\BLEDeck\` folder that runs on any Windows 10/11 machine without Python or a virtualenv.

```bash
cd windows_app
pip install -r requirements-build.txt   # installs PyInstaller
build.bat
```

Output:

```
dist\BLEDeck\
├── BLEDeck.exe      ← launch this
├── icon.ico
├── PyQt5\
├── _internal\       ← bundled Python runtime + dependencies
└── ...
```

Move the entire `dist\BLEDeck\` folder anywhere and run `BLEDeck.exe`. Profiles are stored in `%APPDATA%\BLEDeck\profiles.json` (created on first run), independent of where the exe lives.

| File | Purpose |
|------|---------|
| `bledeck.spec` | PyInstaller spec — controls what gets bundled and how |
| `build.bat` | One-click build script; cleans previous output before building |
| `requirements-build.txt` | Build-time dependency (`pyinstaller>=6.0`; not needed at runtime) |

> **Note:** `build/` and `dist/` are gitignored. Only commit `bledeck.spec` and `build.bat`.

---

## Usage

### Connecting

1. Power on the BLEDeck device.
2. Click **Connect** - the app scans for a device advertising as `BLEDeck` and connects automatically.
3. On connect the app: sends a keep-alive ping, syncs all profile names to the device, then pushes the current profile index and RGB key colors.
4. Enable **Auto-reconnect** to have the app reconnect automatically if the connection drops.

### Profiles

- Use the **Profile** dropdown to switch between profiles.
- Click **New Profile** to create an empty profile.
- Edit the name in the text field, then click **Save Profile**.
- Click **Delete Profile** to remove the current profile (at least one profile must remain).

Switching profiles in the app sends the new profile data to the device. Turning the encoder on the device also switches profiles and notifies the app.

### Keys

The 4×4 grid has two behaviors depending on the active mode (Mode menu):

- **Pad mode** (default) — clicking a key immediately executes its assigned action (command or macro).
- **Edit mode** — clicking a key selects it for configuration. The action panel on the right updates to show that key's settings.

To configure a key, switch to Edit mode first:

1. Click a key button to select it.
2. Set a **Label** - shown on the button in the app.
3. Set a **Color** - enter `R,G,B,Brightness%` directly (e.g. `255,0,0,70`) or use **Pick Color** and the brightness slider. The LED on the device updates immediately.
4. Choose an **Action Type**:
   - **Command** - any shell command or executable path (e.g. `notepad.exe`, `calc.exe`, `"C:\my app\tool.exe"`, `cmd /c echo hello`). Use **Browse** to pick an `.exe`.
   - **Macro** - a recorded sequence of mouse clicks and keystrokes. Click **Edit Macro** to open the macro editor.
5. Click **Save Profile** to persist the configuration.

When a key is pressed on the physical device, the app always executes the assigned command or macro regardless of mode. Command actions and macros run in worker threads, so the GUI never freezes while a long-running command launches.

### Macro Editor

Open the macro editor via **Edit Macro** on any key configured as Macro type.

- **Record** - starts recording. Click targets and type keys; each click and keystroke is captured as a step (mouse movement between clicks is not recorded). Press **Esc** to stop. Recording also auto-stops after 60 s of no input.
- **Stop** - stops an active recording.
- **Test Run** - plays back the current macro immediately (from a background thread).
- **Edit Step** - double-click a step or select it and click Edit Step to change its values (coordinates, key, wait duration, anchor window, etc.).
- **Delete Step** - removes the selected step.
- **Clear** - removes all steps.
- Steps can be **drag-reordered** inside the list.

#### Coordinate anchoring

Mouse clicks are recorded with window-relative or monitor-relative coordinates so playback works even if windows have moved:

| Anchor | Meaning |
|--------|---------|
| `window:<title>` | Relative to the top-left corner of the named window (re-located at playback time) |
| `monitor:<N>` | Relative to the top-left of monitor N (0 = leftmost) — used for desktop/taskbar clicks |
| `abs` | Absolute screen coordinates |

Multi-monitor setups are supported; monitors are indexed by left edge (0 = leftmost).

### Battery

The battery percentage is shown in the top panel next to the connection status. It updates every ~30 seconds while connected. Shows `USB` when no battery is detected.

### Minimize to Tray

Closing or minimising the window hides it to the system tray. Double-click or single-click the tray icon to restore it. Right-click for **Open** / **Quit**.

---

## File Structure

| File | Purpose |
|------|---------|
| `main.py` | `BLEDeckGUI` - main window, BLE lifecycle, notification dispatch, action dispatch |
| `__version__.py` | App metadata (name, version, authors, GitHub URL) used by the About dialog |
| `key_button.py` | `KeyButton(QPushButton)` - individual key widget with color and label state |
| `ble_protocol.py` | Packet builders, parsers, all opcode constants |
| `ble_client.py` | BleakClient/BleakScanner re-export, BLE UUIDs (incl. SERVICE_UUID); returns fake implementations when `BLEDECK_SIM=1` |
| `profile_manager.py` | Load/save `profiles.json` |
| `app_settings.py` | Persistent app-level settings — preferred device MAC, etc. |
| `action_runner.py` | Dispatches commands or macros; per-key re-entrancy guard |
| `macro_models.py` | Immutable step types (`ClickStep`, `KeyStep`, `SleepStep`); JSON serialization |
| `macro_recorder.py` | pynput-based recorder; per-click window/monitor anchor detection |
| `macro_player.py` | Synchronous macro playback; anchor resolution at play time |
| `macro_dialog.py` | `MacroDialog` QDialog - record, edit, reorder, test macro steps |
| `win32_utils.py` | Windows API helpers - window/monitor detection via ctypes |
| `manual.md` | In-app user manual (Help → Manual) |
| `requirements.txt` | Runtime dependencies |
| `requirements-dev.txt` | Test/dev dependencies (`pytest`) |
| `tests/` | Pytest suite - `test_ble_protocol.py`, `test_profile_manager.py`, `test_action_runner.py`, `test_macro_models.py` |
| `profiles.json` | Stored in `%APPDATA%\BLEDeck\`, not in this folder; created on first run |

---

## profiles.json

Profiles are stored in `%APPDATA%\BLEDeck\profiles.json` (created automatically on first run). Format:

```json
[
  {
    "name": "Default",
    "keys": {
      "0": { "label": "Notepad", "color": "100,150,255,70", "action_type": "command", "command": "notepad.exe" },
      "1": { "label": "Calc",    "color": "255,100,100,70", "action_type": "command", "command": "calc.exe" },
      "2": {
        "label": "Macro",
        "color": "0,200,100,70",
        "action_type": "macro",
        "macro": [
          { "type": "sleep", "duration_ms": 500 },
          { "type": "key", "key": "c", "modifiers": ["ctrl"] },
          { "type": "click", "x": 120, "y": 45, "button": "left", "relative_to": "window:Notepad" }
        ]
      }
    }
  }
]
```

Keys with no command and no macro steps are not saved. Color format is `R,G,B,Brightness%` where brightness is `0–100`.

### Schema v1 (since v0.2.2)

New saves wrap the list in a versioned envelope:

```json
{
  "version": 1,
  "profiles": [ /* same profile objects as above */ ]
}
```

- **Backward compatible** — legacy bare-list files still load fine. The next save migrates them to the v1 envelope.
- **Corruption recovery** — if `profiles.json` fails to parse, the file is renamed to `profiles.corrupt.json` and the default profiles are restored, so the app always starts.
- **Storage fallbacks** — the default location is `%APPDATA%\BLEDeck\`. If that directory cannot be created, the app falls back to `~/.bledeck`, then to the system temp directory.

### Macro step types

| Type | Fields |
|------|--------|
| `sleep` | `duration_ms` |
| `key` | `key` (string), `modifiers` (array of `"ctrl"`, `"shift"`, `"alt"`, `"win"`) |
| `click` | `x`, `y`, `button` (`"left"/"right"/"middle"`), `relative_to` (anchor string) |

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
| `0x86` | DEVICE_TELEMETRY | Logs firmware version + uptime + free heap + BLE error count; flags protocol version mismatch |

---

## Limitations

- **Windows only** - uses PyQt5, bleak, and ctypes Win32 APIs; no macOS or Linux support
- **10 profiles max, 16 keys per profile** - protocol limit
- **Macro recorder captures press events only** - release timing and mouse movement paths are not recorded
