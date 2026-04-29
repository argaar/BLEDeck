# BLEDeck Firmware

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
#define OTA_PASSWORD      "your_ota_password"
```

### 2. Build and flash

```bash
pio run --target upload
```

Monitor serial output (115200 baud):

```bash
pio device monitor
```

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
- Voltage divider: 6.2 kΩ (top) / 10 kΩ (bottom), calibrated for 1S LiPo (3.2 V – 4.2 V)
- Reports percentage to the app via `OP_BATTERY_STATUS (0x85)` immediately on connect and after each reading
- `0xFF` is sent when no battery is detected (USB-only)

### Workstation lock
- `OP_LOCK_DEVICE (0x06)` from the app locks/unlocks the device
- When locked: OLED dims, lock icon displayed, all key/encoder events suppressed

### OTA update
1. Long-press the PUSH button to open the settings menu
2. Select **OTA Update** - BLE is shut down, WiFi starts
3. Connect a browser to the device IP (or to `BLEDeck-OTA` AP if WiFi credentials fail)
4. Upload a new `.bin` via the ElegantOTA web interface
5. Device restarts automatically; press BACK to cancel before upload begins
6. OTA session times out after 5 minutes if no upload is started

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
| `credentials.h` | WiFi SSID/password + OTA password (gitignored) |

---

## Configuration Constants (`configuration.h`)

| Constant | Default | Description |
|----------|---------|-------------|
| `MAX_BLE_PAYLOAD_LEN` | 256 | Parser hard limit (matches `MAX_PAYLOAD_LEN` in protocol) |
| `MENU_LONG_PRESS_MS` | 1500 | Hold duration to open settings menu |
| `OTA_TIMEOUT_MS` | 300 000 | OTA idle timeout before auto-restart (ms) |
| `BAT_INTERVAL_S` | 30 000 | Battery ADC read interval (ms) |
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
| `0x81` | Device → App | KEEP_ALIVE_REPLY |
| `0x82` | Device → App | PROFILE_CHANGED |
| `0x83` | Device → App | BUTTON_PRESSED |
| `0x84` | Device → App | KEY_PRESSED |
| `0x85` | Device → App | BATTERY_STATUS |
