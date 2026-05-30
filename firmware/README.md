# BLEDeck Firmware

**Version: 1.2.5** — see [`src/version.h`](src/version.h)

ESP32 firmware for the BLEDeck macro pad. Built with PlatformIO and the Arduino framework. Acts as a BLE GATT peripheral - all logic and configuration are driven by the [Windows app](../windows_app/).

---

## Requirements

- [PlatformIO](https://platformio.org/) (CLI or VS Code extension)
- Board: **ESP32 DevKitC v1 / NodeMCU-32S**

---

## Setup

### 1. Create credentials file

The OTA credentials are not committed. Copy the example and fill it in:

```bash
cp src/credentials.h.example src/credentials.h
```

Edit `src/credentials.h`:

```cpp
#define OTA_WIFI_SSID     "your_wifi_ssid"
#define OTA_WIFI_PASSWORD "your_wifi_password"
#define OTA_HTTP_PASSWORD "your_ota_http_password"
```

### 2. Build and flash

```bash
pio run --target upload
```

Monitor serial output (115200 baud):

```bash
pio device monitor
```

### Optional build environments

`platformio.ini` defines two extra environments for diagnostics:

| Environment | Flag set | Purpose |
|-------------|----------|---------|
| `env:debug` | `-DDEBUG_SERIAL=1` | Verbose serial logging — prints every RX/TX packet, button presses, RGB updates. Default builds keep non-error prints silent. |
| `env:calibrate` | `-DCALIBRATE_BATTERY=1` | Battery-divider calibration mode. Sampling drops to every 5 s and the firmware prints both the current `BAT_CALIBRATION` value and the formula needed to retune it against a multimeter reading. |

Examples:

```bash
pio run -e debug --target upload          # Verbose logging build
pio run -e calibrate --target upload      # Calibration build
pio device monitor                        # Read the serial log
```

Switch back to the default environment by running `pio run --target upload` (or `pio run -e nodemcu-32 --target upload`).

### Native unit tests

Pure-host tests for the protocol parser and OTA rate-limit logic run on
PlatformIO's `native` env (Unity framework, no ESP32 required):

**Prerequisite:** A host C/C++ compiler. PlatformIO bundles only the
xtensa-esp32 toolchain — it does not ship a host gcc. Install one of:

| OS | Option |
|----|--------|
| Windows | [w64devkit](https://github.com/skeeto/w64devkit/releases) (~80 MB zip; extract, add `bin/` to PATH) — lightest |
| Windows | `scoop install gcc` or `choco install mingw` |
| Linux   | usually pre-installed; otherwise `sudo apt install build-essential` (or distro equivalent) |
| macOS   | `xcode-select --install` |

Verify with `gcc --version` before running the command below.

```bash
pio test -e native
```

Tests live under `firmware/test/`. Add new native tests as
`test/<test_name>/test_main.cpp` — PlatformIO discovers each subdirectory
automatically.

---

## Pin Map

| Function | GPIO |
|----------|------|
| OLED SDA | 21 |
| OLED SCL | 22 |
| Encoder A | 35 |
| Encoder B | 34 |
| Button CON | 36 |
| Button BACK | 39 |
| Button PUSH | 27 |
| Keypad rows | 32, 33, 25, 26 |
| Keypad cols | 5, 18, 19, 23 |
| RGB data | 14 |
| Battery ADC | 13 |

**Power & ground:** OLED VCC = 3.3 V. Encoder PUSH input (GPIO 27) is wired to the EC11 SW pin and shares the encoder common GND.

---

## Features

### BLE
- GATT server advertising as `BLEDeck`
- Custom service UUID `4FAFC201-...`
- TX characteristic (notify) for device → app events
- RX characteristic (write) for app → device commands
- TX power set to maximum (+9 dBm) for range
- Auto-restarts advertising on disconnect

### Keypad
- 4×4 matrix, keys labelled `0`–`9`, `A`–`F`
- Each keypress sends `OP_KEY_PRESSED` with the current profile index and key character

### Rotary encoder + buttons
- Turning the encoder cycles through profiles (wraps around)
- **CON** and **BACK** send `OP_BUTTON_PRESSED` with the button name
- **PUSH** short-press sends `OP_BUTTON_PRESSED`
- **PUSH** long-press (≥ 1500 ms) opens the settings menu

### RGB LEDs
- 16 × WS2812B-4020 controlled via NeoPixelBus
- App sets colors per-key (`OP_SET_RGB_KEY`) or all at once (`OP_SET_ALL_RGB_KEYS`)
- Idle animation (rotating rainbow) plays when no app is connected
- Colors reset to defaults on disconnect - the app re-applies them on every connect

### OLED display
- Shows current profile name, BLE connection status, and battery percentage
- Displays a lock icon when the workstation is locked

### Battery monitoring
- ADC reading on GPIO 13 every 30 s (5-sample rolling average)
- Voltage divider: 15 kΩ (top) / 4.3 kΩ (bottom), calibrated for 1S LiPo (3.2 V – 4.2 V). `BAT_R1 = 15000` and `BAT_R2 = 4300` in `configuration.h` match the soldered PCB (the schematic Value fields are wrong — trust the constants, not the schematic).
- Reports percentage to the app via `OP_BATTERY_STATUS (0x85)` immediately on connect and after each reading
- `0xFF` is sent when no battery is detected (USB-only)

#### Battery calibration

The easiest way to calibrate is to flash the `env:calibrate` build. It prints both the current `BAT_CALIBRATION` constant and the value you need to paste back into `configuration.h`, sampling every 5 seconds.

GPIO 13 is on ADC2, which over-reads versus the true input voltage. `BAT_CALIBRATION` in `configuration.h` (currently `0.3607`) absorbs that drift. To tune it on a specific board:

1. Connect over USB and open the serial monitor (115200 baud). The firmware now prints a battery line **unconditionally every 30 s**:
   ```
   [BAT] adc=XXXX mV  vbat=YYYY mV  pct=ZZ
   ```
2. Probe the battery terminals with a multimeter at the same moment and note the real voltage (e.g. `3987 mV`).
3. Recompute the constant:
   ```
   BAT_CALIBRATION_new = multimeter_mV / vbat_mV * BAT_CALIBRATION_current
   ```
   For example, if `vbat = 3700 mV`, multimeter reads `3987 mV` and current `BAT_CALIBRATION = 0.3607`:
   `0.3607 * (3987 / 3700) ≈ 0.3887`.
4. Update `BAT_CALIBRATION` in `configuration.h`, reflash, and verify. A two-point measurement (e.g. ~3.4 V and ~4.1 V) is enough for ±1 % accuracy across the full pack range.

### Workstation lock
- `OP_LOCK_DEVICE (0x06)` from the app locks/unlocks the device
- When locked: OLED dims, lock icon displayed, all key/encoder events suppressed

### OTA update
1. Long-press the PUSH button to open the settings menu
2. Select **OTA Update** - BLE is shut down, WiFi starts
3. Connect a browser to the device IP (or to `BLEDeck-OTA` AP if WiFi credentials fail). The AP fallback uses a **randomized 12-character password** printed on the OLED and over serial.
4. Log in to the ElegantOTA web interface using the `OTA_HTTP_PASSWORD` you set in `credentials.h` and upload a new `.bin`
5. Device restarts automatically. To cancel an in-progress OTA session, **hold BACK for at least 1000 ms** (a brief tap is ignored, so an accidental press doesn't abort a flash).
6. OTA session times out after 5 minutes if no upload is started

### Protocol handshake & telemetry

On every BLE connect, the app sends `OP_HELLO` (0x07) with its app version and the negotiated `PROTOCOL_VERSION`. The firmware replies with `OP_DEVICE_TELEMETRY` (0x86) carrying the firmware version, current uptime, last-reset reason (`esp_reset_reason()`), free heap, and a running BLE-error counter incremented on every malformed packet, send failure, or oversize payload. Mismatched protocol versions surface a CRITICAL warning in the app's log and a status-bar message.

### OTA rate-limit

The OTA HTTP endpoint tracks failed authentication attempts in a small ring buffer. **Five failures within 60 s trigger a 5-minute lockout**, during which all incoming HTTP traffic is dropped (`server_->handleClient()` is skipped). The lockout counter infrastructure is fully wired; ElegantOTA 3.1.7 does not currently expose an auth-failure callback, so the trigger awaits either an upstream hook or a future self-hosted route handler — see the TODO at the top of `OtaManager::loop()`.

### Task watchdog

The ESP32 Arduino framework feeds the IDLE task watchdog automatically as long as `loop()` returns within the configured timeout (default 5 s). BLE callbacks (`onConnect`, `onDisconnect`, RX characteristic write) run on the NimBLE host task — keep them to flag-flipping plus simple state updates; never call `delay()`, I²C, or SPI. OTA mode shuts BLE down before WiFi starts, so the BLE task is dormant during ElegantOTA serving. See the comment block above `setup()` in `main.cpp`.

---

## Source Files

| File | Purpose |
|------|---------|
| `main.cpp` | Setup, main loop, BLE callbacks, all packet handlers |
| `configuration.h` | Pin definitions, BLE limits, battery constants |
| `protocolparser.h` | Protocol definition (all opcodes), binary packet parser |
| `ota_manager.h/.cpp` | WiFi connection, ElegantOTA lifecycle, AP fallback |
| `menu.h` | Minimal OLED scrollable menu |
| `images.h` | XBM bitmaps (splash screen, lock icon) |
| `version.h` | Firmware version constants (`FIRMWARE_VERSION`, `_MAJOR/_MINOR/_PATCH`) |
| `credentials.h` | WiFi SSID/password + OTA password (gitignored) |

---

## Configuration Constants (`configuration.h`)

| Constant | Default | Description |
|----------|---------|-------------|
| `MAX_BLE_PAYLOAD_LEN` | 256 | Parser hard limit (matches `MAX_PAYLOAD_LEN` in protocol) |
| `MENU_LONG_PRESS_MS` | 1500 | Hold duration to open settings menu |
| `OTA_TIMEOUT_MS` | 300 000 | OTA idle timeout before auto-restart (ms) |
| `BAT_INTERVAL_MS` | 30 000 | Battery ADC read interval (ms) |
| `BAT_MIN_V` | 3200 | Minimum LiPo voltage mapped to 0% (mV) |
| `BAT_MAX_V` | 4200 | Maximum LiPo voltage mapped to 100% (mV) |
| `BAT_NUM_READ` | 5 | Rolling average window for ADC readings |

To disable battery support entirely, comment out `#define USE_BATTERY` in `configuration.h`.

---

## Dependencies

| Library | Version | Purpose |
|---------|---------|---------|
| chris--a/Keypad | ^3.1.1 | 4×4 matrix keypad scan |
| maffooclock/ESP32RotaryEncoder | ^1.1.2 | Interrupt-driven rotary encoder |
| thomasfredericks/Bounce2 | ^2.72 | Button debouncing |
| ThingPulse/esp8266-oled-ssd1306 | 4.6.1 | SSD1306 OLED driver |
| makuna/NeoPixelBus | ^2.8.4 | WS2812B RGB LED control |
| rlogiacco/CircularBuffer | ^1.4.0 | Rolling ADC average buffer |
| ayushsharma82/ElegantOTA | ^3.1.7 | Web-based OTA update UI |

---

## Protocol

See [`../docs/ble_protocol_reference.md`](../docs/ble_protocol_reference.md) for the full binary protocol specification.

Quick opcode reference:

| Opcode | Direction | Name |
|--------|-----------|------|
| `0x01` | App → Device | KEEP_ALIVE |
| `0x02` | App → Device | CHANGE_PROFILE |
| `0x03` | App → Device | SYNC_PROFILES |
| `0x04` | App → Device | SET_RGB_KEY |
| `0x05` | App → Device | SET_ALL_RGB_KEYS |
| `0x06` | App → Device | LOCK_DEVICE |
| `0x07` | App → Device | HELLO |
| `0x81` | Device → App | KEEP_ALIVE_REPLY |
| `0x82` | Device → App | PROFILE_CHANGED |
| `0x83` | Device → App | BUTTON_PRESSED |
| `0x84` | Device → App | KEY_PRESSED |
| `0x85` | Device → App | BATTERY_STATUS |
| `0x86` | Device → App | DEVICE_TELEMETRY |
