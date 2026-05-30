# BLEDeck Simulator

Software emulator for the BLEDeck hardware device. Lets developers work on the Windows app without owning a physical device.

Two modes:

| Mode | What it does | When to use |
|------|-------------|-------------|
| **Mode A — Loopback** (default) | In-process fake BLE client. No radio needed. | Daily development, CI, no Bluetooth hardware |
| **Mode B — Real BLE** (`--ble`) | Advertises via WinRT GattServiceProvider. App on a second machine connects normally. | Cross-machine BLE integration testing |

---

## Setup

All commands run from the **project root** (`BLEDeck/`), not from inside `simulator/`.

```bash
# Reuse the windows_app venv (recommended — bleak is already installed there)
windows_app\env\Scripts\activate      # Windows
# source windows_app/env/bin/activate # Linux / macOS

# Or create a dedicated venv
python -m venv simulator/env
simulator\env\Scripts\activate
pip install -r simulator/requirements.txt   # pinned bleak==3.0.2 (+ winrt-* for Mode B) + pytest
```

Mode B (real BLE) uses the WinRT `GattServiceProvider` API via the `winrt-*` packages that `bleak` installs automatically. No separate BLE server library is needed.

Mode A (loopback) needs no extra packages beyond `windows_app/` dependencies.

---

## Mode A — Loopback (default)

Set the environment variable `BLEDECK_SIM=1` and run the app. The app uses `FakeBleakClient` — no radio, instant connect. The simulator CLI starts automatically inside the same process.

| Shell       | Command |
|-------------|---------|
| cmd.exe     | `set BLEDECK_SIM=1 && python windows_app\main.py` |
| PowerShell  | `$env:BLEDECK_SIM=1; python windows_app\main.py` |
| Git Bash    | `BLEDECK_SIM=1 python windows_app/main.py` |

Pick the row matching your shell. Mac/Linux users export the env var the standard way (Git Bash row applies).

No separate simulator process needed. The `sim>` prompt appears in the same terminal.

Alternatively, run the simulator standalone (CLI only — useful for scripting events without launching the full GUI):

```bash
python -m simulator
```

Then in another terminal: `BLEDECK_SIM=1 python windows_app/main.py`. The CLI in the first terminal drives the app.

---

## Mode B — Real BLE (`--ble`)

Runs a GATT server using the WinRT `GattServiceProvider` API. Requires two machines: simulator on Machine A, app on Machine B.

> ⚠️ **Two machines required on Windows.** The Windows BLE stack does not
> allow same-machine self-connection — running `python -m simulator --ble`
> AND `python windows_app/main.py` on the same PC will hang forever with no
> error. The simulator now prints this warning on startup; install the app
> on a second machine to connect.

```bash
python -m simulator --ble
```

Then launch the Windows app normally on another machine (`python windows_app/main.py`). It scans for service UUID `4FAFC201-…`, connects, and behaves identically to a physical device.

The CLI prompt appears after the server starts:

```
INFO: [BLE] Advertising (service UUID: 4FAFC201-...)
sim>
```

### Platform notes

| Platform | Status |
|----------|--------|
| Windows | Primary target. Uses WinRT `GattServiceProvider` — no admin required. Device name is not set in advertisement (WinRT limitation); app connects via service UUID automatically. |
| Linux / macOS | Not supported for Mode B. Use Mode A (loopback) instead. |

---

## CLI Commands (both modes)

```
sim> battery <n>          Send BATTERY_STATUS  (0–100, or -1 for no-battery/USB)
sim> press <idx> <char>   Send KEY_PRESSED     (profile index 0-based, single char)
sim> button <name>        Send BUTTON_PRESSED  (current profile, button name)
sim> profile <idx>        Send PROFILE_CHANGED and update local state (0-based)
sim> state                Print current device state
sim> help                 Show this help
sim> quit                 Exit
```

Examples:

```
sim> battery 72           # device reports 72 % battery
sim> press 0 A            # profile 0, key char 'A' pressed
sim> button macro1        # named button pressed on current profile
sim> profile 2            # switch to profile index 2
sim> state
  profile_index : 2
  profiles      : {1: 'Default', 2: 'Work'}
  locked        : False
  battery       : 72%
  rgb_matrix    : 3/16 keys lit
```

> The simulator automatically replies with `OP_DEVICE_TELEMETRY` whenever it receives an `OP_HELLO` from the app — no manual CLI invocation needed.

---

## File Structure

```
simulator/
  __init__.py          sys.path shim — adds windows_app/ so ble_protocol.py is importable
  __main__.py          Entry point: python -m simulator [--ble]
  device_state.py      DeviceState dataclass (profiles, RGB matrix, lock, battery)
  command_handler.py   Parses PC→Device packets, mutates state, returns response bytes
  event_emitter.py     Builds Device→PC event packets
  ble_server.py        WinRT GattServiceProvider GATT server (Mode B)
  fake_bleak_client.py FakeBleakClient + FakeBleakScanner (Mode A)
  _context.py          Module-level singletons shared between app and CLI in Mode A
  cli.py               Async REPL used by both modes
  requirements.txt
  tests/
    conftest.py
    test_command_handler.py   every opcode + edge cases
    test_event_emitter.py     round-trip packet assertions
    test_fake_client.py       FakeBleakClient API surface
```

`command_handler.py` and `event_emitter.py` import `ble_protocol.py` directly from `windows_app/` — single source of truth for opcodes and packet layout.

---

## Running Tests

```bash
# from repo root (uses windows_app venv)
python -m pytest simulator/tests/ -v
```

No external dependencies beyond `pytest`.

---

## How It Works

### Mode B (real BLE)

```
[simulator process]
  BLEServer (WinRT GattServiceProvider)
    ├── advertises service UUID 4FAFC201-... (connectable + discoverable)
    ├── RX write → command_handler.handle() → state mutation
    │   KEEP_ALIVE write → KEEP_ALIVE_REPLY notification sent back
    └── TX notify ← event_emitter packets triggered by CLI commands
  CLI (asyncio REPL)
    └── "battery 80" → emit.battery_status(80) → BLEServer.send_event()

[app process — unmodified]
  BleakScanner.discover(service_uuids=[...]) → finds simulated device
  BleakClient.connect() → GATT connection established
  RX write OP_HELLO → command_handler stores app version → reply OP_DEVICE_TELEMETRY via event_emitter
  handle_notification() ← TX notifications from simulator
```

### Mode A (loopback)

```
[single process — app + simulator]
  BLEDECK_SIM=1 → ble_client.py returns FakeBleakClient
  FakeBleakClient.connect()          → immediate success
  RX write OP_HELLO → command_handler stores app version → reply OP_DEVICE_TELEMETRY via event_emitter
  FakeBleakClient.write_gatt_char()  → command_handler.handle()
  FakeBleakClient.start_notify()     → stores handle_notification callback
  FakeBleakClient.push_event()       → calls handle_notification directly
  CLI (_run_sim_cli asyncio task)
    └── "press 0 A" → emit.key_pressed(0,'A') → push_event()
```

---

## Protocol Reference

[`docs/ble_protocol_reference.md`](../docs/ble_protocol_reference.md) — full opcode table and payload layouts.

When a new opcode is added to the protocol, update `command_handler.py` or `event_emitter.py` alongside `firmware/`, `windows_app/ble_protocol.py`, and the docs.

---

## Hardening notes

Recent robustness changes worth knowing about when reading or extending the simulator:

- **CHANGE_PROFILE stores the profile name.** The handler now persists the name carried by `OP_CHANGE_PROFILE` (it was previously parsed and dropped), matching firmware behaviour.
- **Malformed and oversized packets are dropped silently.** Anything that fails framing or exceeds the 256-byte payload cap is logged at DEBUG level and ignored — the simulator does not crash on garbage input.
- **CLI input validation.** `battery`, `press`, and `profile` validate their arguments before emitting any packet (range checks, single-character keys, numeric profile indices). Invalid input prints an error and emits nothing.
- **`_context.reset_state()`** clears the shared `DeviceState` / client singletons between tests. The pytest suite uses it for isolation; reach for it in new fixtures.
- **`bleak==3.0.2` pinned** in `requirements.txt` together with the explicit `winrt-*` sub-packages used by Mode B, so the WinRT GATT server build is reproducible.
- v0.1.2: `OP_HELLO` (0x07) handler stores the app version and replies with `OP_DEVICE_TELEMETRY` (0x86); telemetry payload is fully synthetic (zero uptime, zero heap) — it exists for app-side handshake testing
