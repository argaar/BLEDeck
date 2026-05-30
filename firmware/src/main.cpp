#include "configuration.h"
#include "protocolparser.h"
#include "menu.h"
#include "ota_manager.h"
#include "version.h"
#include <esp_system.h>
#include <images.h>

#include <Keypad.h>

#include <ESP32RotaryEncoder.h>
#include <Bounce2.h>

#include <Wire.h>
#include "SSD1306Wire.h"
#include "OLEDDisplay.h"

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <BLESecurity.h>

#include <NeoPixelBus.h>

#ifdef USE_BATTERY
#include "CircularBuffer.hpp"
#endif

#include <vector>

// Protocol Parser
ProtocolParser parser;

// Profiles - can be updated from Windows app
int currentProfile = 0;
const int MAX_PROFILES = 10;  // Support up to 10 profiles
String profileNames[MAX_PROFILES] = {"Default"};  // Initialize first profile, rest will be set by app
int profileCount = 1;  // Track number of profiles received from app

// BLE Connection Management
BLEServer* pServer;
BLECharacteristic* pTxCharacteristic;
bool deviceConnected = false;
bool oldDeviceConnected = false;
unsigned long lastPingTime = 0;
unsigned long connectionStartTime = 0;

// BATTERY PROPERTIES
#ifdef USE_BATTERY
static uint32_t last_read_bat = 0;
CircularBuffer<float, BAT_NUM_READ> bat_readings;
int batteryLevel = 0;
#endif

// Misc
bool workstationLocked = false;
unsigned long lastColorShift = 0;

// Counts BLE-side errors (parse failures, malformed payloads, send aborts).
// Surfaced via OP_DEVICE_TELEMETRY so the app can flag a flaky link.
uint16_t bleErrorCount = 0;

// Menu & OTA state
SimpleMenu* activeMenu = nullptr;
OtaManager* otaManager = nullptr;
bool otaActive = false;

// Packed RGB + brightness (W = 0..100 %) — 4 bytes per key.
// Replaces an earlier String-based representation that caused heap
// fragmentation on long uptime (every per-key update reallocated four
// temporary String objects).
struct RGBW {
  uint8_t r;
  uint8_t g;
  uint8_t b;
  uint8_t w;
};

// OLED
SSD1306Wire * display;

void oledUpdate() {
  display->clear();

  display->setFont(ArialMT_Plain_16);
  display->drawString(0, 0, "Current profile:");

  display->setFont(ArialMT_Plain_24);
  display->drawString(0, 18, profileNames[currentProfile]);

  char dev_status[40];
  #ifdef USE_BATTERY
  snprintf(dev_status, sizeof(dev_status), "BT: %s | Bat: %d%%", deviceConnected ? "CONN" : "DISCONN", batteryLevel);
  #else
  snprintf(dev_status, sizeof(dev_status), "BT: %s", deviceConnected ? "CONN" : "DISCONN");
  #endif
  display->setFont(ArialMT_Plain_10);
  display->drawString(0, 50, dev_status);

  display->display();
}

void oledUpdateLockedStatus() {
  if (workstationLocked) {
    display->clear();
    display->drawXbm((display->getWidth()-LOCK_IMAGE_WIDTH)/2, (display->getHeight()-LOCK_IMAGE_HEIGHT)/2, LOCK_IMAGE_WIDTH, LOCK_IMAGE_HEIGHT, LOCK_IMAGE);
    display->display();
  } else {
    oledUpdate();
  }
}

// BLE Send Helpers
void sendBinaryPacket(uint8_t opcode, const uint8_t* payload, uint16_t payloadLen) {
  if (!deviceConnected) {
    Serial.println("Cannot send - device not connected");
    bleErrorCount++;
    return;
  }

  if (!pTxCharacteristic) {
    Serial.println("Cannot send - characteristic not available");
    bleErrorCount++;
    return;
  }

  if (payloadLen > MAX_BLE_PAYLOAD_LEN) {
    Serial.printf("Error: payload too large (%d)\n", payloadLen);
    bleErrorCount++;
    return;
  }

  // Build packet: START + OPCODE + LENGTH(2B) + PAYLOAD
  uint8_t packet[4 + MAX_BLE_PAYLOAD_LEN];
  packet[0] = START_BYTE;
  packet[1] = opcode;
  packet[2] = (payloadLen >> 8) & 0xFF;  // Length high byte
  packet[3] = payloadLen & 0xFF;          // Length low byte

  if (payloadLen > 0 && payload != nullptr) {
    memcpy(packet + 4, payload, payloadLen);
  }

  pTxCharacteristic->setValue(packet, 4 + payloadLen);
  pTxCharacteristic->notify();
  #ifdef DEBUG_SERIAL
  Serial.printf("TX -> Opcode: 0x%02X, Length: %d\n", opcode, payloadLen);
  #endif
}

void sendKeepAliveReply() {
  sendBinaryPacket(OP_KEEP_ALIVE_REPLY, nullptr, 0);
  lastPingTime = millis();
}

void sendProfileChanged(uint8_t profileIndex) {
  if (workstationLocked) {
    #ifdef DEBUG_SERIAL
    Serial.println("Workstation Locked - no actions allowed");
    #endif
    return;
  }
  sendBinaryPacket(OP_PROFILE_CHANGED, &profileIndex, 1);
}

void sendButtonPressed(const char* buttonName) {
  if (workstationLocked) {
    #ifdef DEBUG_SERIAL
    Serial.println("Workstation Locked - no actions allowed");
    #endif
    return;
  }

  // Payload: profile_index(1B) + button_name_length(1B) + button_name
  uint8_t nameLen = (uint8_t)min((size_t)MAX_BUTTON_NAME_LEN, strlen(buttonName));
  uint8_t payload[2 + MAX_BUTTON_NAME_LEN];
  payload[0] = currentProfile;
  payload[1] = nameLen;
  memcpy(payload + 2, buttonName, nameLen);

  sendBinaryPacket(OP_BUTTON_PRESSED, payload, 2 + nameLen);
}

void sendKeyPressed(char key) {
  if (workstationLocked) {
    #ifdef DEBUG_SERIAL
    Serial.println("Workstation Locked - no actions allowed");
    #endif
    return;
  }

  // Payload: profile_index(1B) + key(1B)
  uint8_t payload[2];
  payload[0] = currentProfile;
  payload[1] = (uint8_t)key;

  sendBinaryPacket(OP_KEY_PRESSED, payload, 2);
}

void sendDeviceTelemetry() {
  if (!deviceConnected) return;
  const char* fw_ver = FIRMWARE_VERSION;  // from version.h
  uint8_t fw_len = (uint8_t)strlen(fw_ver);
  uint32_t uptime_ms = millis();
  uint8_t reset_reason = (uint8_t)esp_reset_reason();
  uint32_t free_heap = ESP.getFreeHeap();
  uint16_t err_count = bleErrorCount;

  uint8_t payload[1 + 1 + 64 + 4 + 1 + 4 + 2];
  size_t off = 0;
  payload[off++] = PROTOCOL_VERSION;
  payload[off++] = fw_len;
  if (fw_len > 64) fw_len = 64;
  memcpy(payload + off, fw_ver, fw_len);
  off += fw_len;
  payload[off++] = (uptime_ms >> 24) & 0xFF;
  payload[off++] = (uptime_ms >> 16) & 0xFF;
  payload[off++] = (uptime_ms >>  8) & 0xFF;
  payload[off++] = (uptime_ms      ) & 0xFF;
  payload[off++] = reset_reason;
  payload[off++] = (free_heap >> 24) & 0xFF;
  payload[off++] = (free_heap >> 16) & 0xFF;
  payload[off++] = (free_heap >>  8) & 0xFF;
  payload[off++] = (free_heap      ) & 0xFF;
  payload[off++] = (err_count >> 8) & 0xFF;
  payload[off++] = (err_count     ) & 0xFF;

  sendBinaryPacket(OP_DEVICE_TELEMETRY, payload, off);
}

// BATTERY MGMT
#ifdef USE_BATTERY
void sendBatteryStatus() {
  // 0xFF signals "no battery / USB-only" to the app
  uint8_t pct = (batteryLevel == 999) ? 0xFF : (uint8_t)batteryLevel;
  sendBinaryPacket(OP_BATTERY_STATUS, &pct, 1);
}

void batteryLoop(){
    if (0 == last_read_bat || millis() - last_read_bat > BAT_INTERVAL_MS) {

        uint16_t v = analogReadMilliVolts(BAT_PIN);
        if (v!=0) {
            bat_readings.push(v);
            float bat_values = 0.0;
            for (int i = 0; i < bat_readings.size(); ++i) {
                bat_values = bat_values + bat_readings[i];
            }
            float avg_adc_mv = bat_values / bat_readings.size();
            float avg_bat_voltage = avg_adc_mv * ( (BAT_R1 + BAT_R2) / BAT_R2 ) * BAT_CALIBRATION;
            float percent = (avg_bat_voltage - BAT_MIN_V) * 100.0 / (BAT_MAX_V - BAT_MIN_V);

            // Clamp between 0% and 100%
            if (percent < 0) percent = 0;
            if (percent > 100) percent = 100;
            // Always log raw + computed values so the divider can be calibrated.
            // Compare printed Vbat against a multimeter reading; if off, adjust
            // BAT_R1 / BAT_R2 / BAT_CALIBRATION in configuration.h.
            Serial.printf("[BAT] adc=%.0fmV vbat=%.0fmV pct=%.0f\n",
                          avg_adc_mv, avg_bat_voltage, percent);
            #ifdef CALIBRATE_BATTERY
            // Guided calibration build (pio run -e calibrate). Probe the
            // battery terminals with a multimeter and feed the reading into
            // the formula below; paste the result into configuration.h.
            float theoretical_mult = (BAT_R1 + BAT_R2) / BAT_R2;
            Serial.printf(
                "[CALIBRATE] current BAT_CALIBRATION=%.4f, theoretical_mult=%.4f\n"
                "[CALIBRATE] new BAT_CALIBRATION = multimeter_mV / (%.0f * %.4f)\n"
                "[CALIBRATE] e.g. if multimeter reads 4035 mV -> %.4f\n",
                (float)BAT_CALIBRATION, theoretical_mult,
                avg_adc_mv, theoretical_mult,
                4035.0f / (avg_adc_mv * theoretical_mult));
            #endif
            batteryLevel = int(percent);
        } else {
            #ifdef DEBUG_SERIAL
            Serial.println("No battery!");
            #endif
            batteryLevel = 999;
        }
        last_read_bat = millis();
        oledUpdate();
        if (deviceConnected) {
            sendBatteryStatus();
        }
    }
}
#endif

// RGB
NeoPixelBus<NeoGrbFeature, NeoWs2812xMethod> rgb_keys(RGB_NUM, RGB_PIN);

const RGBW defaultRgbColors[RGB_NUM] = {
  {255,   0,   0, 80},
  {255,  96,   0, 80},
  {255, 191,   0, 80},
  {255, 255,   0, 80},
  {191, 255,   0, 80},
  { 96, 255,   0, 80},
  {  0, 255,   0, 80},
  {  0, 255,  96, 80},
  {  0, 255, 191, 80},
  {  0, 191, 255, 80},
  {  0,  96, 255, 80},
  {  0,   0, 255, 80},
  { 96,   0, 255, 80},
  {191,   0, 255, 80},
  {255,   0, 191, 80},
  {255,   0,  96, 80}
};

RGBW rgbColors[RGB_NUM];

// WS2812B refresh limiter: bursts of per-key updates coalesce into ~60 Hz
// strip writes. Faster than the eye can resolve, frees ~7.7 ms per dropped
// Show() call during slider drags / fast colour edits.
static bool     rgbShowPending_ = false;
static uint32_t rgbLastShowMs_  = 0;
constexpr uint32_t kRgbMinFrameIntervalMs = 16;

void resetRgbColors() {
  memcpy(rgbColors, defaultRgbColors, sizeof(rgbColors));
}

void rgbUpdateColors(const RGBW* colorArray, int idx = -1) {
  if (idx < 0) { // negative idx means update in bulk
    for (size_t i = 0; i < RGB_NUM; i++) {
      RgbColor color = RgbColor(colorArray[i].r, colorArray[i].g, colorArray[i].b);
      rgb_keys.SetPixelColor(i, color.Dim(map(colorArray[i].w, 0, 100, 0, 255)));
    }
  } else {
    RgbColor color = RgbColor(colorArray[idx].r, colorArray[idx].g, colorArray[idx].b);
    rgb_keys.SetPixelColor(idx, color.Dim(map(colorArray[idx].w, 0, 100, 0, 255)));
  }
  // Defer the actual Show() to rgbFlush() so back-to-back updates coalesce.
  rgbShowPending_ = true;
}

// Pump the deferred-refresh state machine. Call from loop() every tick.
// No-op if nothing changed or the limiter window has not elapsed.
void rgbFlush() {
  if (!rgbShowPending_) return;
  uint32_t now = millis();
  if (now - rgbLastShowMs_ < kRgbMinFrameIntervalMs) return;
  rgb_keys.Show();
  rgbLastShowMs_ = now;
  rgbShowPending_ = false;
}

void rotateColors(RGBW* colors, size_t count) {
  if (count < 2) return;

  RGBW first = colors[0];
  for (size_t i = 1; i < count; i++) {
    colors[i - 1] = colors[i];
  }
  colors[count - 1] = first;
}

// Handlers
void handlePacket(const ParsedPacket &pkt) {
  #ifdef DEBUG_SERIAL
  Serial.printf("RX <- Opcode: 0x%02X, Length: %d\n", pkt.opcode, pkt.length);
  #endif

  // Reset ping timer on any received message
  lastPingTime = millis();

  switch (pkt.opcode) {
    case OP_KEEP_ALIVE: {
      // Keep alive ping - send reply
      sendKeepAliveReply();
      break;
    }

    case OP_CHANGE_PROFILE: {
      // Payload: profile_index(1B) + name_length(1B) + name
      if (pkt.length < 2) {
        Serial.println("Error: CHANGE_PROFILE packet too short");
        bleErrorCount++;
        break;
      }

      uint8_t profileIndex = pkt.payload[0];
      uint8_t nameLength = pkt.payload[1];

      if (pkt.length < 2 + nameLength) {
        Serial.println("Error: CHANGE_PROFILE packet incomplete");
        bleErrorCount++;
        break;
      }

      // Extract profile name
      String profileName = "";
      for (int i = 0; i < nameLength; i++) {
        profileName += (char)pkt.payload[2 + i];
      }

      // Store profile name (profile index is 1-based on the wire)
      if (profileIndex == 0 || profileIndex > MAX_PROFILES) {
        Serial.printf("Error: Invalid profile index %d\n", profileIndex);
        bleErrorCount++;
        break;
      }
      int idx = profileIndex - 1;
      profileNames[idx] = profileName;
      if (idx >= profileCount) {
        profileCount = idx + 1;
      }
      currentProfile = idx;
      oledUpdate();
      #ifdef DEBUG_SERIAL
      Serial.printf("Applied CHANGE_PROFILE -> %d (%s)\n", idx, profileNames[idx].c_str());
      #endif
      break;
    }

    case OP_SYNC_PROFILES: {
      // Payload: count(1B) + [index(1B) + name_len(1B) + name]*count
      if (pkt.length < 1) {
        Serial.println("Error: SYNC_PROFILES packet too short");
        bleErrorCount++;
        break;
      }

      uint8_t count = pkt.payload[0];
      #ifdef DEBUG_SERIAL
      Serial.printf("Syncing %d profiles\n", count);
      #endif

      int offset = 1;
      for (int i = 0; i < count; i++) {
        if (offset + 2 > pkt.length) break;

        uint8_t profileIndex = pkt.payload[offset++];
        uint8_t nameLen = pkt.payload[offset++];

        if (offset + nameLen > pkt.length) break;

        String name = "";
        for (int j = 0; j < nameLen; j++) {
          name += (char)pkt.payload[offset++];
        }

        // Store profile name (1-based on the wire; index 0 reserved)
        if (profileIndex == 0 || profileIndex > MAX_PROFILES) {
          Serial.printf("SYNC: bad profile index %d, aborting\n", profileIndex);
          bleErrorCount++;
          break;
        }
        int idx = profileIndex - 1;
        profileNames[idx] = name;
        if (idx >= profileCount) {
          profileCount = idx + 1;
        }
        #ifdef DEBUG_SERIAL
        Serial.printf("Synced profile %d: '%s'\n", profileIndex, name.c_str());
        #endif
      }

      // Update display with current profile
      oledUpdate();
      break;
    }

    case OP_SET_RGB_KEY: {
      // Payload: key_index(1B) + R(1B) + G(1B) + B(1B) + W(1B)
      if (pkt.length != 5) {
        Serial.println("Error: SET_RGB_KEY invalid length");
        bleErrorCount++;
        break;
      }

      uint8_t keyIndex = pkt.payload[0];
      uint8_t r = pkt.payload[1];
      uint8_t g = pkt.payload[2];
      uint8_t b = pkt.payload[3];
      uint8_t w = pkt.payload[4];

      // Validate indices
      if (keyIndex >= RGB_NUM) {
        Serial.printf("Error: Invalid key index %d\n", keyIndex);
        bleErrorCount++;
        break;
      }

      // Update the color for this key
      rgbColors[keyIndex] = {r, g, b, w};

      #ifdef DEBUG_SERIAL
      Serial.printf("Set key %d to RGBW(%d,%d,%d,%d)\n", keyIndex, r, g, b, w);
      #endif

      // Update the LED immediately
      rgbUpdateColors(rgbColors, keyIndex);
      break;
    }

    case OP_SET_ALL_RGB_KEYS: {
      // Payload: 16 x RGBW (64 bytes total)
      if (pkt.length != 64) {
        Serial.printf("Error: SET_ALL_RGB_KEYS invalid length (expected 64, got %d)\n", pkt.length);
        bleErrorCount++;
        break;
      }

      #ifdef DEBUG_SERIAL
      Serial.println("Setting all 16 RGB keys");
      #endif

      // Update all 16 keys
      for (size_t i = 0; i < RGB_NUM; i++) {
        rgbColors[i] = {
          pkt.payload[i * 4],
          pkt.payload[i * 4 + 1],
          pkt.payload[i * 4 + 2],
          pkt.payload[i * 4 + 3]
        };
      }

      // Update all LEDs at once
      rgbUpdateColors(rgbColors);
      #ifdef DEBUG_SERIAL
      Serial.println("All RGB keys updated");
      #endif
      break;
    }

    case OP_LOCK_DEVICE: {
      // Payload: lock_flag(1B) - 0x01=lock, 0x00=unlock
      if (pkt.length != 1) {
        Serial.println("Error: LOCK_DEVICE invalid length");
        bleErrorCount++;
        break;
      }

      uint8_t lockFlag = pkt.payload[0];

      if (lockFlag == 0x01) {
        workstationLocked = true;
        display->setBrightness(50);
        oledUpdateLockedStatus();
        #ifdef DEBUG_SERIAL
        Serial.println("Device LOCKED");
        #endif
      } else if (lockFlag == 0x00) {
        workstationLocked = false;
        display->setBrightness(255);
        oledUpdate();
        #ifdef DEBUG_SERIAL
        Serial.println("Device UNLOCKED");
        #endif
      } else {
        Serial.printf("Error: Invalid lock flag 0x%02X\n", lockFlag);
        bleErrorCount++;
      }
      break;
    }

    case OP_HELLO: {
      // Payload: protocol_version(1B) + app_version_len(1B) + app_version(N)
      if (pkt.length < 2) {
        Serial.println("Error: HELLO packet too short");
        bleErrorCount++;
        break;
      }
      uint8_t appProtoVer = pkt.payload[0];
      uint8_t appVerLen = pkt.payload[1];
      if (pkt.length < (uint16_t)(2 + appVerLen)) {
        Serial.println("Error: HELLO packet incomplete");
        bleErrorCount++;
        break;
      }
      #ifdef DEBUG_SERIAL
      char appVer[65];
      uint8_t copyLen = appVerLen < 64 ? appVerLen : 64;
      memcpy(appVer, &pkt.payload[2], copyLen);
      appVer[copyLen] = '\0';
      Serial.printf("HELLO: app proto=%u, app version='%s'\n",
                    (unsigned)appProtoVer, appVer);
      #else
      (void)appProtoVer;
      #endif
      // Always reply with telemetry — app uses this for version-mismatch detection.
      sendDeviceTelemetry();
      break;
    }

    default:
      #ifdef DEBUG_SERIAL
      Serial.printf("Unknown opcode: 0x%02X\n", pkt.opcode);
      #endif
      bleErrorCount++;
      break;
  }
}

void handleProfileChange() {
  #ifdef DEBUG_SERIAL
  Serial.printf("Profile changed to: %d (%s)\n", currentProfile, profileNames[currentProfile].c_str());
  #endif

  // Preserve lock-screen icon when locked. Previously the encoder could
  // clear the lock icon by triggering oledUpdate() unconditionally.
  if (workstationLocked) {
    oledUpdateLockedStatus();
    return;
  }

  oledUpdate();
  if (deviceConnected) {
    #ifdef DEBUG_SERIAL
    Serial.printf("Sending profile change notification: %d\n", currentProfile);
    #endif
    sendProfileChanged(currentProfile);
  } else {
    #ifdef DEBUG_SERIAL
    Serial.println("Device not connected - skipping profile notification");
    #endif
  }
}

// BLE Pairing — display passkey on OLED, host enters it once to bond.
// Bonding persists across reboots (stored in NVS) so the user only sees this
// the first time a new central tries to connect.
class DeckSecurityCallbacks : public BLESecurityCallbacks {
  uint32_t onPassKeyRequest() override { return 0; }

  void onPassKeyNotify(uint32_t pass_key) override {
    display->clear();
    display->setFont(ArialMT_Plain_10);
    display->drawString(0, 0, "Enter pairing PIN:");
    char pin[8];
    snprintf(pin, sizeof(pin), "%06u", (unsigned)pass_key);
    display->setFont(ArialMT_Plain_24);
    display->drawString(0, 20, pin);
    display->display();
    #ifdef DEBUG_SERIAL
    Serial.printf("Pair PIN: %s\n", pin);
    #endif
  }

  bool onConfirmPIN(uint32_t pin) override {
    // Display the numeric comparison value on OLED so the user can verify
    // it matches the number shown on the connecting PC. Returning true after
    // showing it is safe: an attacker would have to display the same 6-digit
    // value on the spoofed central, which the user can detect by comparing
    // both screens. Do not return false — Windows uses Numeric Comparison
    // even for ESP_IO_CAP_OUT and returning false aborts pairing entirely.
    char pin_str[8];
    snprintf(pin_str, sizeof(pin_str), "%06u", (unsigned)pin);
    display->clear();
    display->setFont(ArialMT_Plain_10);
    display->drawString(0, 0, "Confirm pairing:");
    display->setFont(ArialMT_Plain_24);
    display->drawString(0, 20, pin_str);
    display->display();
    #ifdef DEBUG_SERIAL
    Serial.printf("NumericComparison PIN: %s\n", pin_str);
    #endif
    return true;
  }
  bool onSecurityRequest() override { return true; }

  void onAuthenticationComplete(esp_ble_auth_cmpl_t cmpl) override {
    Serial.printf("BLE auth: %s\n", cmpl.success ? "OK" : "FAIL");
    oledUpdate();   // restore main screen regardless of outcome
  }
};

// BLE Callbacks with improved connection handling
class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) override {
    deviceConnected = true;
    connectionStartTime = millis();
    lastPingTime = millis();
    #ifdef DEBUG_SERIAL
    Serial.println("BLE Connected");
    #endif

    #ifdef USE_BATTERY
    last_read_bat = 0;  // force batteryLoop() to fire on next iteration so the host gets an immediate reading
    #endif
  }

  void onDisconnect(BLEServer* pServer) override {
    deviceConnected = false;
    oldDeviceConnected = true;
    #ifdef DEBUG_SERIAL
    Serial.println("BLE Disconnected - Resetting to default state");
    #endif

    // Reset to default state
    currentProfile = 0;
    profileCount = 1;

    // Clear all profile names and reset to default
    for (int i = 0; i < MAX_PROFILES; i++) {
      profileNames[i] = (i == 0) ? "Default" : "";
    }

    // Reset RGB colors to default
    resetRgbColors();
    rgbUpdateColors(rgbColors);

    // Update OLED display
    oledUpdate();

    #ifdef DEBUG_SERIAL
    Serial.println("Reset complete - back to default profile");
    #endif

    // Configure advertising with better parameters
    // Note: delay for BLE stack cleanup is handled in loop() via oldDeviceConnected guard
    BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
    pAdvertising->addServiceUUID("4FAFC201-1FB5-459E-8FCC-C5C9C331914B");
    pAdvertising->setScanResponse(false);
    pAdvertising->setMinPreferred(0x0);
    pAdvertising->setMinPreferred(0x1F);

    pServer->startAdvertising();
    #ifdef DEBUG_SERIAL
    Serial.println("Restarted advertising");
    #endif
  }
};

class RxCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* pCharacteristic) override {
    std::string rx = pCharacteristic->getValue();
    if (rx.empty()) return;

    #ifdef DEBUG_SERIAL
    Serial.printf("BLE RX: %d bytes - ", rx.length());
    // Print first 8 bytes for quick inspection
    for (int i = 0; i < min((int)rx.length(), 8); i++) {
        Serial.printf("%02X ", (uint8_t)rx[i]);
    }
    Serial.println();
    #endif

    ParsedPacket pkt;
    int packetCount = 0;

    for (uint8_t b : rx) {
        if (parser.feed(b, pkt)) {
            packetCount++;
            #ifdef DEBUG_SERIAL
            Serial.printf("Parsed packet #%d\n", packetCount);
            #endif
            handlePacket(pkt);
        }
    }

    if (packetCount == 0) {
        Serial.println("Warning: No complete packets parsed from received data");
        bleErrorCount++;
    } else {
        #ifdef DEBUG_SERIAL
        Serial.printf("Successfully parsed %d packet(s)\n", packetCount);
        #endif
    }
  }
};

// ENCODER
Bounce2::Button btn_encoder_con = Bounce2::Button();
Bounce2::Button btn_encoder_back = Bounce2::Button();
Bounce2::Button btn_encoder_push = Bounce2::Button();
RotaryEncoder rotaryEncoder( DI_ENCODER_A, DI_ENCODER_B, -1 );

volatile bool turnedRightFlag = false;
volatile bool turnedLeftFlag = false;

void knobCallback( long value ) {
  if (workstationLocked) {
    #ifdef DEBUG_SERIAL
    Serial.println("Workstation Locked - no actions allowed");
    #endif
    return;
  }

	if( turnedRightFlag || turnedLeftFlag )
		return;

	switch( value )	{
		case 1:
	  		turnedRightFlag = true;
		break;
		case -1:
	  		turnedLeftFlag = true;
		break;
	}

	rotaryEncoder.setEncoderValue( 0 );
}

// KEYS
char hexaKeys[4][4] = {
  {'0','1','2','3'},
  {'4','5','6','7'},
  {'8','9','A','B'},
  {'C','D','E','F'}
};

byte rowPins[4] = {ROW_PIN_1, ROW_PIN_2, ROW_PIN_3, ROW_PIN_4};
byte colPins[4] = {COL_PIN_1, COL_PIN_2, COL_PIN_3, COL_PIN_4};
Keypad* keypad;

// Menu items
static const SimpleMenu::Item MENU_ITEMS[] = {
  {"OTA Update"},
  {"Cancel"}
};
static const int MENU_ITEM_COUNT = 2;

// Generate a one-shot AP password so the fallback AP never reuses the
// HTTP-auth secret. Restricted to an unambiguous alphabet (no 0/O, 1/I/l).
static void generateApPassword(char* out, size_t len) {
  static const char alphabet[] = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  static const size_t alpha_n = sizeof(alphabet) - 1;
  for (size_t i = 0; i + 1 < len; i++) {
    out[i] = alphabet[esp_random() % alpha_n];
  }
  out[len - 1] = '\0';
}

void enterOtaMode() {
  #ifdef DEBUG_SERIAL
  Serial.println("Entering OTA mode");
  #endif
  display->clear();
  display->setFont(ArialMT_Plain_10);
  display->drawString(16, 28, "Starting OTA...");
  display->display();
  delay(300);

  // Deinit BLE to free the shared radio for WiFi.
  // The BT controller needs ~500ms to fully release before WiFi can start.
  BLEDevice::deinit(true);
  delay(500);

  char apPassword[OTA_AP_PASSWORD_LEN + 1];
  generateApPassword(apPassword, sizeof(apPassword));

  otaManager = new OtaManager(display);
  otaManager->begin(OTA_WIFI_SSID, OTA_WIFI_PASSWORD,
                    apPassword, OTA_HTTP_PASSWORD, OTA_HOSTNAME);
  otaActive = true;  // always succeeds: AP fallback guarantees a network is up
}

void openMenu() {
  #ifdef DEBUG_SERIAL
  Serial.println("Opening settings menu");
  #endif
  activeMenu = new SimpleMenu(display, MENU_ITEMS, MENU_ITEM_COUNT);
}

void closeMenu() {
  delete activeMenu;
  activeMenu = nullptr;
  oledUpdate();
}

void handleMenuInput() {
  // BACK exits menu
  if (btn_encoder_back.pressed()) {
    closeMenu();
    return;
  }

  // Encoder scrolls through items
  if (turnedRightFlag) {
    turnedRightFlag = false;
    activeMenu->scroll(1);
  } else if (turnedLeftFlag) {
    turnedLeftFlag = false;
    activeMenu->scroll(-1);
  }

  // Short PUSH press selects item
  if (btn_encoder_push.pressed()) {
    int sel = activeMenu->cursor();
    closeMenu();
    if (sel == 0) enterOtaMode();
    // sel == 1 (Cancel) just closes the menu
  }
}

// Task watchdog notes
// -------------------
// The ESP32 Arduino framework feeds the IDLE task watchdog automatically as
// long as `loop()` returns within the configured timeout (default 5 s). BLE
// callbacks (`ServerCallbacks::onConnect`, `onDisconnect`) and the RX
// characteristic write callback run on the NimBLE host task; they must NOT
// block — keep their bodies to flag-flipping plus simple state updates.
// OTA mode shuts BLE down before starting WiFi, so the BLE task is dormant
// while ElegantOTA handles HTTP requests. If you add a long-running operation
// to any of the above paths, call `delay(1)` or `vTaskDelay(1)` to yield, or
// disable the WDT for that task explicitly.
void setup() {
  // Misc
  Serial.begin(115200);
  #ifdef DEBUG_SERIAL
  Serial.println("BLEDeck Firmware Starting...");
  #endif

  // Oled
  display = new SSD1306Wire(SSD1306_ADDRESS, I2C_SDA, I2C_SCL);

  display->init();
  display->flipScreenVertically();

  display->clear();
  display->drawXbm((display->getWidth()-LOGO_IMAGE_WIDTH)/2, (display->getHeight()-LOGO_IMAGE_HEIGHT)/2, LOGO_IMAGE_WIDTH, LOGO_IMAGE_HEIGHT, LOGO_IMAGE);
  display->display();

  // RGB
  rgb_keys.Begin();
  rgb_keys.Show();

  // Keys
  keypad = new Keypad(makeKeymap(hexaKeys), rowPins, colPins, 4, 4);

  // Encoder
	rotaryEncoder.setEncoderType(EncoderType::HAS_PULLUP);
	rotaryEncoder.setBoundaries( -1, 1, false );
	rotaryEncoder.onTurned( &knobCallback );
	rotaryEncoder.begin();

  // Buttons
  btn_encoder_con.attach(DI_ENCODER_CON, INPUT_PULLUP);
  btn_encoder_con.interval(BUTTON_DEBOUNCE_MS);
  btn_encoder_con.setPressedState(LOW);

  btn_encoder_back.attach(DI_ENCODER_BACK, INPUT_PULLUP);
  btn_encoder_back.interval(BUTTON_DEBOUNCE_MS);
  btn_encoder_back.setPressedState(LOW);

  btn_encoder_push.attach(DI_ENCODER_PUSH, INPUT_PULLUP);
  btn_encoder_push.interval(BUTTON_DEBOUNCE_MS);
  btn_encoder_push.setPressedState(LOW);

  // BLE with improved configuration
  BLEDevice::init("BLEDeck");
  BLEDevice::setMTU(247);  // larger MTU so notifies up to ~244B don't truncate

  // Set BLE power to maximum for better range
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_ADV, ESP_PWR_LVL_P9);
  //esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_SCAN, ESP_PWR_LVL_P9);

  // Enforce pairing+bonding before any GATT writes — any nearby BLE central
  // would otherwise be free to send LOCK / SET_RGB / CHANGE_PROFILE packets.
  BLEDevice::setEncryptionLevel(ESP_BLE_SEC_ENCRYPT_MITM);
  BLEDevice::setSecurityCallbacks(new DeckSecurityCallbacks());

  BLESecurity* sec = new BLESecurity();
  sec->setAuthenticationMode(ESP_LE_AUTH_REQ_SC_MITM_BOND);
  sec->setCapability(ESP_IO_CAP_OUT);   // device displays passkey
  sec->setInitEncryptionKey(ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK);

  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new ServerCallbacks());

  BLEService *service = pServer->createService("4FAFC201-1FB5-459E-8FCC-C5C9C331914B");

  pTxCharacteristic = service->createCharacteristic(
    "BEB5483E-36E1-4688-B7F5-EA07361B26A8",
    BLECharacteristic::PROPERTY_NOTIFY);
  pTxCharacteristic->setAccessPermissions(ESP_GATT_PERM_READ_ENC_MITM);
  pTxCharacteristic->addDescriptor(new BLE2902());

  BLECharacteristic *rx = service->createCharacteristic(
    "EAB5483E-36E1-4688-B7F5-EA07361B26A9",
    BLECharacteristic::PROPERTY_WRITE);
  rx->setAccessPermissions(ESP_GATT_PERM_WRITE_ENC_MITM);
  rx->setCallbacks(new RxCallbacks());

  service->start();

  // Configure advertising with better parameters
  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID("4FAFC201-1FB5-459E-8FCC-C5C9C331914B");
  pAdvertising->setScanResponse(false);
  pAdvertising->setMinPreferred(0x0);
  pAdvertising->setMinPreferred(0x1F);
  pServer->getAdvertising()->start();

  // Profiles
  oledUpdate();

  // RGB — initialize working palette from the defaults before first paint.
  resetRgbColors();
  rgbUpdateColors(rgbColors);

  #ifdef USE_BATTERY
  // Battery
  analogSetPinAttenuation(BAT_PIN, ADC_11db); // 0.1-3.1V range
  #endif

  #ifdef DEBUG_SERIAL
  Serial.println("Firmware ready - Advertising started");
  #endif
  lastPingTime = millis();
}

void loop() {
  // Always update buttons so menu and long-press work regardless of BLE state
  btn_encoder_con.update();
  btn_encoder_back.update();
  btn_encoder_push.update();

  // OTA mode: hand off entirely to OTA manager
  if (otaActive) {
    // BACK cancels OTA - but never interrupt an in-progress upload.
    // Require ≥1000 ms hold (release with long duration) to avoid accidental cancel.
    if (btn_encoder_back.released() &&
        btn_encoder_back.previousDuration() >= 1000 &&
        !otaManager->isUpdating()) {
      #ifdef DEBUG_SERIAL
      Serial.println("OTA cancelled by user");
      #endif
      delete otaManager;
      otaManager = nullptr;
      otaActive = false;
      ESP.restart();
      return;
    }
    otaManager->loop();
    // Timeout only fires when idle (not mid-upload)
    if (otaManager->timedOut() && !otaManager->isUpdating()) {
      delete otaManager;
      otaManager = nullptr;
      otaActive = false;
      #ifdef DEBUG_SERIAL
      Serial.println("OTA timeout - restarting");
      #endif
      ESP.restart();
    }
    delay(10);
    return;
  }

  // Menu mode: handle navigation and selection
  if (activeMenu != nullptr) {
    handleMenuInput();
    delay(10);
    return;
  }

  // Long press PUSH (>MENU_LONG_PRESS_MS) opens settings menu
  if (!workstationLocked &&
      btn_encoder_push.released() &&
      btn_encoder_push.previousDuration() > MENU_LONG_PRESS_MS) {
    openMenu();
    return;
  }

  // Handle connection state changes
  if (!deviceConnected && oldDeviceConnected) {
    delay(500); // Give the bluetooth stack time to clean up
    oldDeviceConnected = deviceConnected;
    #ifdef DEBUG_SERIAL
    Serial.println("Connection cleanup completed");
    #endif
  }

  // Debug: Log connection status changes
  static bool lastConnectedState = false;
  if (deviceConnected != lastConnectedState) {
    #ifdef DEBUG_SERIAL
    Serial.printf("Connection state changed: %s\n", deviceConnected ? "CONNECTED" : "DISCONNECTED");
    #endif
    lastConnectedState = deviceConnected;
  }

  // Connection timeout check - disconnect if app stops pinging
  if (deviceConnected && (millis() - lastPingTime > BLE_PING_TIMEOUT_MS)) {
    #ifdef DEBUG_SERIAL
    Serial.println("Connection timeout - no ping received");
    #endif
    pServer->disconnect(pServer->getConnId());
    // Defensive: ensure cleanup branch runs even if onDisconnect callback misfires
    deviceConnected = false;
    oldDeviceConnected = true;
  }

  if (deviceConnected) {
    if (btn_encoder_con.pressed()){
      #ifdef DEBUG_SERIAL
      Serial.println("CON PRESSED");
      #endif
      sendButtonPressed("CON");
    }

    if (btn_encoder_back.pressed()){
      #ifdef DEBUG_SERIAL
      Serial.println("BACK PRESSED");
      #endif
      sendButtonPressed("BACK");
    }

    // Short PUSH release sends event; long press was already handled above
    if (btn_encoder_push.released() &&
        btn_encoder_push.previousDuration() <= MENU_LONG_PRESS_MS) {
      #ifdef DEBUG_SERIAL
      Serial.println("PUSH PRESSED");
      #endif
      sendButtonPressed("PUSH");
    }

    // Read keypad input
    char key = keypad->getKey();
    if (key && !workstationLocked) {
      #ifdef DEBUG_SERIAL
      Serial.println(key);
      #endif
      sendKeyPressed(key);
    }

    // Perform encoder action — but never rotate profiles while locked.
    if (workstationLocked) {
      turnedRightFlag = false;
      turnedLeftFlag = false;
    } else if (turnedRightFlag) {
      turnedRightFlag = false;
      #ifdef DEBUG_SERIAL
      Serial.println("Right ->");
      #endif
      currentProfile++;
      if (currentProfile >= profileCount) {
        currentProfile = 0;  // Wrap to first profile
      }
      handleProfileChange();
    } else if (turnedLeftFlag) {
      turnedLeftFlag = false;
      #ifdef DEBUG_SERIAL
      Serial.println("<- Left");
      #endif
      currentProfile--;
      if (currentProfile < 0) {
        currentProfile = profileCount - 1;  // Wrap to last profile
      }
      handleProfileChange();
    }
  } else {
    // Play idle RGB animation when not connected.
    // Note: rgbUpdateColors() now defers the strip write — rgbFlush() below
    // performs the actual Show() within the same loop iteration.
    if (millis() - lastColorShift >= 200) {   // 200 ms passed
      lastColorShift = millis();
      rotateColors(rgbColors, RGB_NUM);
      rgbUpdateColors(rgbColors);
    }
  }

  // Coalesce any pending WS2812B updates into a single ~60 Hz refresh.
  rgbFlush();

  #ifdef USE_BATTERY
  // Update adc reading
  batteryLoop();
  #endif

  // Active path: yield to the BLE host task without sleeping. Drops keypress→
  // dispatch latency from ~10 ms worst case to ~1 ms. Disconnected path keeps
  // the longer delay as a power-save (idle RGB animation only needs ~5 Hz).
  if (deviceConnected) {
    vTaskDelay(1);
  } else {
    delay(10);
  }
}
