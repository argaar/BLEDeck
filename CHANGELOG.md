# Changelog

Covers: `enclosure`, `firmware`, `pcb`, `simulator`, `windows_app`.

## Latest releases (2026-05-30)

| Component | Version | Headline |
|-----------|---------|----------|
| `firmware`    | **v1.2.5** | `loop()` yield when connected; WS2812B refresh coalesced at 60 Hz |
| `windows_app` | **v0.2.6** | `pyproject.toml` packaging; unified `run-tests` scripts; Help → Forget paired device + view-source buttons; truthful pytest pin |
| `simulator`   | **v0.1.2** | `OP_HELLO` handler replies with `OP_DEVICE_TELEMETRY` |
| `pcb`         | v1.1       | (last release — no changes this cycle) |
| `enclosure`   | v1.0.0     | (last release — no changes this cycle) |

Update this table on every release. Detailed bullets per version live in the
per-component sections below.

---

## windows_app

### v0.2.6 — 2026-05-30
- Security: bumped `markdown` `3.7` → `3.10.2` (PYSEC-2026-89 — unhandled `AssertionError` DoS on malformed Markdown) and `pytest` `<9` → `>=9.0.3` (CVE-2025-71176 — predictable `/tmp/pytest-of-*` dir on UNIX); lifted the stale `pytest-asyncio<1` cap to `>=1.4` and `pytest-benchmark` to `>=5`. Clears all three Dependabot alerts; 258 tests still green under pytest 9
- DX: `pyproject.toml` at repo root — single `pip install -e .[dev]` (or `.[dev,build]`) replaces the three `requirements*.txt` install dance; declares `windows_app`/`simulator`/`debug` packages and registers `bledeck-decode` as a console script
- DX: cross-platform `setup-dev.sh` mirrors `setup-dev.bat`; both now install runtime + dev + build deps and verify with `pytest` in one shot
- DX: `run-tests.bat` / `run-tests.sh` at repo root — unified runner for Python suites + firmware native Unity tests; clean SKIP when `pio` is absent
- DX: Help menu now has **Forget paired device** — clears `preferred_device_mac` in `app_settings.json` with a confirmation dialog (no more hand-editing JSON)
- DX: Help → Manual dialog gets two new ActionRole buttons — **View source on GitHub** and **Open in browser** — so users can share / print a section
- DX: `Connect → Device not found` now prints 3 actionable hints (BT enabled? device on? troubleshooting doc link) and status bar reads "Device not found — see logs"
- DX: `bench_protocol.py` `importorskip` carries an explicit install hint instead of a silent skip
- DX: `requirements-dev.txt` pin truthified — `pytest>=8.3,<9` matches the installed version (the prior `pytest==9.0.3` pin was a lie; pytest-asyncio caps pytest <9)
- DX: README + simulator/README ship a three-row `BLEDECK_SIM=1` syntax table (cmd / PowerShell / Git Bash) so PowerShell users no longer get bitten by the `&&` separator
- DX: `docs/troubleshooting.md` adds a callout pointing readers at `Help → Enable Debug` when triaging no-connect reports
- DX: `firmware/README.md` Native unit tests section spells out the host-gcc prerequisite (w64devkit / scoop / choco / apt / xcode-select)
- DX: `CHANGELOG.md` gets a "Latest releases" table at the top — one-glance view of the current HEAD across every component
- Legal: added repo-root `LICENSE` (MIT) and reconciled the README License section + `pyproject.toml` (`0.2.6`, was a stale `0.2.5`) to all state MIT consistently; `bledeck.spec` now bundles `LICENSE` into the packaged app
- Docs: corrected three README inaccuracies — `profiles.json` lives in `%APPDATA%\BLEDeck\` (not next to the exe), the macro recorder captures clicks + keystrokes (not mouse movement) and auto-stops after 60 s, and the simulator dedicated-venv install now points at the pinned `simulator/requirements.txt`
- Docs: `CONTRIBUTING.md` carries the full protocol-change file table inline (no longer delegating to a non-shipped file); PR template points at it
- Test: added `tests/test_macro_player.py` (14) — anchor resolution (window/monitor/abs), the `_resolve_key` multi-char safety guard, and click-offset/modifier-order playback; closes the only untested business-logic module
- Test: benchmarks are now actually deselected by default via `addopts = "-m 'not benchmark'"` (declaring the marker alone never skipped them once `pytest-benchmark` was installed)
- Refactor: hoisted the per-notification opcode-label dict to a module constant `_OP_NAMES` (no realloc per packet)
- Resilience: window-close BLE-disconnect poll now self-terminates at a ~10 s ceiling, so a wedged BLE stack can never make the window un-closable
- Cleanup: removed an unused `pathlib.Path` import in `app_settings.py`

### v0.2.5
- Perf: connection bootstrap waits on `OP_DEVICE_TELEMETRY` and `OP_KEEP_ALIVE_REPLY` instead of two hardcoded `asyncio.sleep(0.5)` calls. First-key-ready latency after Connect drops from ~1.6 s to <300 ms on a healthy link
- Perf: added `_opcode_waiters` map + `_await_opcode(opcode, timeout)` helper; `handle_notification` resolves the matching future as soon as a packet arrives (does not short-circuit dispatch)
- Perf: colour / brightness edits debounced via a 50 ms `QTimer` (`_color_send_timer` + `_pending_color_packet`); slider drag now collapses to ~20 Hz BLE writes instead of one per integer tick
- Perf: `self.log()` short-circuits ping/pong / `[PING]` / `[PONG]` lines when the Debug Log panel is hidden — saves the `data.hex()` interpolation + QTextEdit append on every keep-alive cycle
- Perf: rotating file handler wrapped with `QueueHandler` + `QueueListener` — disk I/O runs on a background thread, GUI thread never blocks on a slow `bledeck.log` write; listener stopped cleanly in `closeEvent`
- Perf: `ActionRunner` reuses a shared `ThreadPoolExecutor(max_workers=4)` instead of spawning a fresh `threading.Thread` per device keypress; `atexit` shutdown with `cancel_futures=True` so stuck shell commands no longer block interpreter exit
- Added: `tests/bench_protocol.py` (NEW) — 9 microbenchmarks under `pytest-benchmark`; skips cleanly when the package is missing. Default `pytest` runs still exclude them via the `benchmark` marker
- Added: `pytest-benchmark>=4,<6` to `requirements-dev.txt`

### v0.2.4
- Refactor: extracted `RISKY_COMMAND_TOKENS` + `collect_risky_commands()` into new `command_safety.py` module (pure function, no GUI dependency); `BLEDeckGUI._collect_risky_commands` is now a one-line shim
- Added tests: `test_app_settings.py` (7), `test_log_filter.py` (6 — pins the `[PING]`/`[PONG]` regression), `test_command_safety.py` (9), `test_macro_recorder.py` (4)
- Added contract / integration tests: `test_contract.py` (11) — app builders ↔ simulator handler byte equivalence; `test_decoder_contract.py` (10) — every builder decoded correctly by `debug/protocol_decoder.py`; `test_handshake.py` (4) — full connect sequence (HELLO → TELEMETRY → SYNC → CHANGE → SET_ALL_RGB)
- Added: `pytest-asyncio>=0.24,<1` to `requirements-dev.txt` (needed for `test_cli.py` in simulator)
- Note: pytest transitively downgraded to `8.4.2` to satisfy `pytest-asyncio` upper bound on pytest 9

### v0.2.3
- Added: rotating file log at `%APPDATA%\BLEDeck\logs\bledeck.log` (5 × 20 MB, 100 MB cap); `KEEP_ALIVE` traffic filtered out for readability
- Added: app sends `OP_HELLO` on connect; firmware replies with `OP_DEVICE_TELEMETRY`; mismatched `PROTOCOL_VERSION` surfaces a CRITICAL log line
- Added: exponential backoff on auto-reconnect — 10 s → doubles → capped at 5 min; resets after a successful connect
- Added: preferred device MAC pinned in `%APPDATA%\BLEDeck\app_settings.json` after first successful connect; multiple BLEDecks in range now favour the previously-used one
- Added: `WTS_SESSION_LOCK` subscription replaces the 2.5 s workstation-lock poll — sub-50 ms lock-detection latency
- Added: profiles.json load surfaces a `QMessageBox.warning` listing high-risk command tokens (`powershell`, `cmd /c`, `curl … | iex`, etc.) so untrusted files cannot fire silently
- Added: macro recorder auto-stops after 60 s of idle time to limit accidental capture
- Documentation: new `docs/troubleshooting.md`; macro capture risk callout added to `manual.md`

### v0.2.2
- Added: `BLEPacket.parse` enforces `MAX_PAYLOAD_LEN = 256` cap and rejects truncated frames (parity with firmware + simulator)
- Added: `tests/test_hardening.py` — 13 regression tests covering `_resource_path`, atomic save, schema v1 round-trip, and `BUTTON_PRESSED` parser contract
- Added: profiles.json schema v1 — file now wraps `{"version": 1, "profiles": [...]}`; legacy bare-list files load and migrate on next save
- Added: `requirements-dev.txt` for test-only dependencies (`pytest` moved out of runtime requirements)
- Added: `_resource_path()` resolver — icon and manual now load correctly in PyInstaller frozen builds via `_MEIPASS`
- Added: `.corrupt.json` backup on profiles.json parse failure (defaults restored, GUI keeps starting)
- Added: `%APPDATA%` mkdir failure falls back to `~/.bledeck` then `tempfile.gettempdir()/bledeck`
- Added: atomic write of profiles.json (tmp + `os.replace`) — no half-written files on crash
- Added: command actions launched in worker thread (no GUI freeze on slow paths)
- Added: `MacroDialog` Test Run button disabled while playback active; signal-driven re-enable
- Added: `_sample: True` marker on the three pre-filled default keys (Notepad/Calc/Explorer) for future first-run UX
- Fixed: truncated `APP_VERSION` string in `__version__.py` (`"0.2."` → `"0.2.1"`)
- Fixed: `parse_key_pressed` rejects non-hex bytes (firmware only emits 0-9/A-F)
- Fixed: `BUTTON_PRESSED` bounds-checks profile index (parity with KEY_PRESSED)
- Fixed: `_render_manual_html` ImportError fallback now returns escaped `<pre>` (no raw markdown)
- Changed: profile-name buffer raised to 39 B (matches firmware buffer minus NUL); warns on truncation
- Changed: narrowed bare `except Exception` in `win32_utils.py`; `asyncio.CancelledError` re-raised in notification handler

### v0.2.1
- Fixed: GUI applications (notepad, calc, etc.) launched hidden due to `STARTF_USESHOWWINDOW`; now uses `CREATE_NO_WINDOW` which suppresses console flash without hiding GUI windows
- Fixed: Pad mode key clicks ran the edit-selection handler instead of executing the assigned action; added `_on_key_click()` routing (Pad → execute action, Edit → select key for config)
- Added: installer script (`build.bat` + `bledeck.spec`) to package app as standalone Windows executable via PyInstaller
- Added: `__version__.py` as single source of truth for app name, version, and metadata

### v0.2.0
- Added: macro recorder and player — captures mouse clicks and keystrokes with window/monitor-relative coordinate anchoring
- Added: `MacroDialog` — record, edit, reorder, delete, and test-run macro steps
- Added: two action types per key: Command (shell) and Macro
- Added: multi-monitor support; monitors indexed by left edge (0 = leftmost)
- Added: macro step types: `ClickStep`, `KeyStep`, `SleepStep` with JSON serialization
- Added: `pynput`-based recorder with per-click window anchor detection
- Added: `macro_player.py` with anchor resolution at play time

### v0.1.0
- Initial release
- BLE scan, connect, auto-reconnect
- 4×4 key grid with per-key label, RGBW color, and shell command action
- Profile management: create, rename, save, delete; stored in `%APPDATA%\BLEDeck\profiles.json`
- Live RGB sync on color change
- Battery indicator
- System tray minimize
- Profile switching via encoder on device (PROFILE_CHANGED event)
- Workstation lock/unlock via LOCK_DEVICE opcode

---

## simulator

### v0.1.2 — 2026-05-30
- Added: `OP_HELLO` command handler — replies with `OP_DEVICE_TELEMETRY` using simulator-provided fields
- Added: `event_emitter.device_telemetry()` builder
- Tests: new HELLO/telemetry round-trip tests under `simulator/tests/test_command_handler.py`
- Tests (post-release): `tests/test_cli.py` (18) — REPL exit paths (`q`/`quit`/`exit`/EOF/blank), `battery` clamping, `press` validation, `profile` bounds, `help`/`state`/unknown-command paths

### v0.1.1
- Fixed: CHANGE_PROFILE handler now parses and stores the name payload (was dropped — diverged from firmware)
- Added: input validation on CLI `battery`/`press`/`profile` commands (rejects out-of-range / malformed values before emitting)
- Added: malformed and truncated packets logged at DEBUG with offending bytes
- Added: oversized payloads (>256 B) rejected to match firmware `MAX_PAYLOAD_LEN`
- Added: `_handle_write` wraps cmd dispatch in try/except with raw-byte logging (deferral always completes)
- Added: `_context.reset_state()` helper for test isolation; autouse fixture in `conftest.py`
- Changed: `FakeBleakClient` registers itself on `connect()`, not `__init__` (avoids ghost active clients across reconnects)
- Changed: user-facing fallback messages in `__main__.py` use `logger` instead of `print`
- Fixed: misleading `--loopback` help text (loopback is the default — no flag needed)
- Pinned: `bleak==3.0.2` with required `winrt-*` sub-packages
- Removed: dead `_BLESS_AVAILABLE` flag and `bless` compatibility comments

### v0.1.0
- Initial release
- Mode A (loopback): `FakeBleakClient` / `FakeBleakScanner` in-process fake — no Bluetooth needed; activated by `BLEDECK_SIM=1`
- Mode B (real BLE): WinRT `GattServiceProvider` GATT server via `--ble` flag; requires two machines
- CLI REPL: `battery`, `press`, `button`, `profile`, `state`, `help`, `quit` commands
- `DeviceState` dataclass for profiles, RGB matrix, lock, battery
- `command_handler.py` handles all PC→Device opcodes (KEEP_ALIVE, CHANGE_PROFILE, SYNC_PROFILES, SET_RGB_KEY, SET_ALL_RGB_KEYS, LOCK_DEVICE)
- `event_emitter.py` builds Device→PC events (BATTERY_STATUS, KEY_PRESSED, BUTTON_PRESSED, PROFILE_CHANGED)

#### Known limitations
- Mode B (real BLE GATT server) is Windows-only (WinRT-backed)
- Same-machine BLE self-connection is not supported by Windows; Mode B requires two machines

---

## firmware

### v1.2.5 — 2026-05-30
- Perf: `loop()` now yields with `vTaskDelay(1)` when a BLE session is active, keeping the existing 10 ms `delay()` only on the disconnected idle path. Keypress→dispatch latency drops from ~10 ms worst case to ~1 ms while connected; the disconnected idle animation keeps its power-save sleep
- Perf: WS2812B strip refresh coalesced at ~60 Hz via a `rgbShowPending_` flag + `rgbFlush()` pump called from `loop()`. Bursts of per-key `OP_SET_RGB_KEY` updates (e.g. brightness-slider drag) collapse into one strip write per ~16 ms instead of one per packet — saves ~7.7 ms per dropped `Show()` call
- `kRgbMinFrameIntervalMs = 16` constant exposes the limiter window in `main.cpp`

### v1.2.4
- Refactor: extracted OTA auth-failure rate-limit logic from `OtaManager` into a header-only `OtaRateLimiter` struct in `ota_manager.h` so it can be exercised by host-side Unity tests. Algorithm unchanged; `OtaManager` now delegates `isLockedOut()` / `recordFailure()` to the struct
- Added: `[env:native]` PlatformIO environment for host-side Unity tests (`pio test -e native` — no ESP32 required)
- Added tests: `test/test_protocol_parser/test_main.cpp` (6) — zero-length, single-byte, garbage resync, oversize drop, multi-byte, max-size edge case
- Added tests: `test/test_ota_rate_limit/test_main.cpp` (5) — lockout after 5 failures within 60 s, spread-failure non-lockout, lockout clears after 5 min, recordFailure safe during active lockout
- Documentation: `firmware/README.md` now documents the `native` test env

### v1.2.3
- Added: `OP_HELLO` (0x07) PC → Device opcode for protocol version handshake
- Added: `OP_DEVICE_TELEMETRY` (0x86) Device → PC opcode — sent on every `OP_HELLO`; payload includes firmware version, uptime, reset reason, free heap, BLE error count
- Added: `PROTOCOL_VERSION = 1` constant in `protocolparser.h`; bump for breaking protocol changes
- Added: OTA HTTP auth rate-limit infrastructure (`OtaRateLimiter`) — 5 failed attempts within 60 s arm a 5-minute lockout. The lockout gate is checked in `OtaManager::loop()`, but ElegantOTA 3.1.7 exposes no auth-failure callback, so failures are not yet recorded and the lockout stays dormant until the library gains an `onAuthFail` hook or the upload routes are self-hosted
- Added: BLE error counter exposed via `OP_DEVICE_TELEMETRY`
- Documentation: ESP32 task watchdog assumptions now spelled out in `main.cpp` above `setup()`

### v1.2.2
- Added: BLE MTU negotiated to 247 in `setup()` (avoids silent truncation of notifies >20 B)
- Added: `BAT_CALIBRATION` constant in `configuration.h` to absorb the ESP32 ADC2/attenuation over-read on GPIO 13. Empirically tuned to `0.3607`; tune per board against a multimeter
- Added: unconditional `[BAT] adc=… mV vbat=… mV pct=…` serial line every 30 s for calibration (no more `DEBUG_SERIAL` gate on this one line)
- Added: `MAX_PROFILES = 10` documented in `protocolparser.h` protocol comment block
- Fixed: battery divider constants `BAT_R1=15000` / `BAT_R2=4300` now match the soldered PCB (the schematic Value fields are wrong)
- Fixed: `BAT_INTERVAL_S` renamed to `BAT_INTERVAL_MS` (name matches units)
- Fixed: OLED brightness restored to 255 on unlock (was 100 — screen stayed dim after first lock)
- Fixed: ping-timeout disconnect now sets `deviceConnected` / `oldDeviceConnected` flags defensively so the loop's cleanup branch always runs
- Fixed: OTA cancel via BACK requires ≥1000 ms hold (avoids restart between user click and ElegantOTA `onStart` callback)
- Fixed: `sendBatteryStatus()` body now wrapped in `#ifdef USE_BATTERY` for symmetry
- Fixed: `rgbColors` "all-keys" sentinel changed from magic `99` to `-1` (safe against future `RGB_NUM` growth)
- Changed: `rgbColors` reworked from `std::vector<String>` to packed `RGBW[]` (4 B per key) — eliminates per-update heap fragmentation; `splitColorsString` parser removed
- Fixed: `credentials.h.example` renamed `OTA_PASSWORD` → `OTA_HTTP_PASSWORD` with explanatory comment
- Changed: `splitColorsString` converted to `template<size_t N>` — array-size mismatch caught at compile time
- Changed: removed dead `try/catch` around `notify()` (ESP32 Arduino is built `-fno-exceptions`)
- Changed: non-error `Serial.print*` calls gated behind `#ifdef DEBUG_SERIAL` (off by default)
- Changed: OTA AP password length bumped from 8 to 12 characters (~60 bits entropy)
- Pinned: `platform = espressif32@6.9.0` and `ElegantOTA=3.1.7` for reproducible builds

### v1.2.1
- Added: OTA update support via ElegantOTA (long-press encoder PUSH → settings menu → OTA Update)
- Added: WiFi STA connect with AP fallback (`BLEDeck-OTA`) for OTA mode
- Added: custom partition table (`partitions_ota.csv`) for larger OTA partition
- Added: `version.h` — single source of truth for firmware version constants
- Fixed: workstation lock detection and display
- Fixed: connection timeout after `BLE_PING_TIMEOUT_MS` (30 s) without KEEP_ALIVE

### v1.1.0 — matches pcb v1.1
- Enabled 16 WS2812B RGB LEDs (full 4×4 matrix)
- Changed key layout to match PCB v1.1 footprint
- Added battery voltage reporting (`OP_BATTERY_STATUS 0x85`) with 5-sample rolling average
- TX power set to +9 dBm maximum

### v1.0.0
- Initial release
- BLE GATT server advertising as `BLEDeck`
- Binary framed protocol (START 0xAA | OPCODE | LENGTH(2) | PAYLOAD)
- Profile management: SYNC_PROFILES, CHANGE_PROFILE, PROFILE_CHANGED
- Per-key RGB scaffolding: SET_RGB_KEY, SET_ALL_RGB_KEYS opcodes (full 16-LED matrix lit in v1.1.0)
- Key press events: KEY_PRESSED (profile_index + key_char)
- Named button events: BUTTON_PRESSED (CON, BACK, PUSH)
- Rotary encoder cycles profiles; idle RGB animation when disconnected
- SSD1306 OLED: profile name, connection status, battery
- Workstation lock: LOCK_DEVICE suppresses key/encoder events, dims OLED

---

## pcb

### v1.1
- Fixed key switch footprint connections
- Fixed LED traces for WS2812B-4020 side-emitting layout
- Fixed OLED footprint and pin connections
- Rerouted all tracks and vias
- Evenly spaced key grid

### v1.0
- Initial two-layer KiCad design
- ESP32 DevKitC v1, 16 Gateron key switches, SSD1306 OLED, EC11 encoder
- Battery connector with 15 kΩ / 4.3 kΩ voltage divider on GPIO 13
- Gerbers for JLCPCB included

---

## enclosure

### v1.0.0
- Initial 3D printable enclosure in PLA
- Parts: `PushButton.stl` (×2), `KeyboardLayer.stl`, `BatteryTop.stl`, `BatteryLayer.stl`, `Bottom.stl`
