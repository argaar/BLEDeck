#include "configuration.h"
#include "protocolparser.h"
#include "menu.h"
#include "ota_manager.h"
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

// Menu & OTA state
SimpleMenu* activeMenu = nullptr;
OtaManager* otaManager = nullptr;
bool otaActive = false;

void splitColorsString(String data, char delimiter, int *result, int expectedParts) {
  int start = 0;
  int end = 0;

  for (int i = 0; i < expectedParts; i++) {
    end = data.indexOf(delimiter, start);
    if (end == -1) end = data.length(); // last part

    result[i] = data.substring(start, end).toInt();
    start = end + 1;
  }
}

// OLED
SSD1306Wire * display;

void oledUpdate() {
  display->clear();

  char profile_text[17];
  snprintf(profile_text, sizeof(profile_text), "Current profile:");
  display->setFont(ArialMT_Plain_16);
  display->drawString(0, 0, profile_text);

  char profile_name[40];
  snprintf(profile_name, sizeof(profile_name), "%s", profileNames[currentProfile]);
  display->setFont(ArialMT_Plain_24);
  display->drawString(0, 18, profile_name);

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
    return;
  }

  if (!pTxCharacteristic) {
    Serial.println("Cannot send - characteristic not available");
    return;
  }

  if (payloadLen > MAX_BLE_PAYLOAD_LEN) {
    Serial.printf("Error: payload too large (%d)\n", payloadLen);
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

  try {
    pTxCharacteristic->setValue(packet, 4 + payloadLen);
    pTxCharacteristic->notify();
    Serial.printf("TX -> Opcode: 0x%02X, Length: %d\n", opcode, payloadLen);
  } catch (...) {
    Serial.println("Error sending notification");
    deviceConnected = false;
  }
}

void sendKeepAliveReply() {
  sendBinaryPacket(OP_KEEP_ALIVE_REPLY, nullptr, 0);
  lastPingTime = millis();
}

void sendProfileChanged(uint8_t profileIndex) {
  if (workstationLocked) {
    Serial.println("Workstation Locked - no actions allowed");
    return;
  }
  sendBinaryPacket(OP_PROFILE_CHANGED, &profileIndex, 1);
}

void sendButtonPressed(const char* buttonName) {
  if (workstationLocked) {
    Serial.println("Workstation Locked - no actions allowed");
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
    Serial.println("Workstation Locked - no actions allowed");
    return;
  }

  // Payload: profile_index(1B) + key(1B)
  uint8_t payload[2];
  payload[0] = currentProfile;
  payload[1] = (uint8_t)key;

  sendBinaryPacket(OP_KEY_PRESSED, payload, 2);
}

// BATTERY MGMT
void sendBatteryStatus() {
  // 0xFF signals "no battery / USB-only" to the app
  uint8_t pct = (batteryLevel == 999) ? 0xFF : (uint8_t)batteryLevel;
  sendBinaryPacket(OP_BATTERY_STATUS, &pct, 1);
}

#ifdef USE_BATTERY
void batteryLoop(){
    if (0 == last_read_bat || millis() - last_read_bat > BAT_INTERVAL_S) {

        uint16_t v = analogReadMilliVolts(BAT_PIN);
        if (v!=0) {
            bat_readings.push(v);
            float bat_values = 0.0;
            for (int i = 0; i < bat_readings.size(); ++i) {
                bat_values = bat_values + bat_readings[i];
            }
            float avg_bat_voltage = (bat_values / bat_readings.size()) * ( (BAT_R1 + BAT_R2) / BAT_R2 );
            float percent = (avg_bat_voltage - BAT_MIN_V) * 100.0 / (BAT_MAX_V - BAT_MIN_V);

            // Clamp between 0% and 100%
            if (percent < 0) percent = 0;
            if (percent > 100) percent = 100;
            char batmgmt[24] = "" ;
            sprintf (batmgmt, "Bat: %.1fV - %.0f%%", avg_bat_voltage/1000, percent);
            Serial.println(batmgmt);
            batteryLevel = int(percent);
        } else {
            Serial.println("No battery!");
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

const std::vector<String> defaultRgbColors = {
  "255,0,0,80",
  "255,96,0,80",
  "255,191,0,80",
  "255,255,0,80",
  "191,255,0,80",
  "96,255,0,80",
  "0,255,0,80",
  "0,255,96,80",
  "0,255,191,80",
  "0,191,255,80",
  "0,96,255,80",
  "0,0,255,80",
  "96,0,255,80",
  "191,0,255,80",
  "255,0,191,80",
  "255,0,96,80"
};

std::vector<String> rgbColors = defaultRgbColors;

void rgbUpdateColors(const std::vector<String>& colorArray, int idx = 99) {
  if (idx==99) {// we want to update in bulk since 99 is an out of range number
    for (int i=0; i<colorArray.size(); i++) {
      int values[4];
      String colors = colorArray[i];
      splitColorsString(colors, ',', values, 4);
      RgbColor color = RgbColor(values[0], values[1], values[2]);
      rgb_keys.SetPixelColor(i, color.Dim(map(values[3], 0, 100, 0, 255)));
    }
  } else {
    int values[4];
    String colors = colorArray[idx];
    splitColorsString(colors, ',', values, 4);
    RgbColor color = RgbColor(values[0], values[1], values[2]);
    rgb_keys.SetPixelColor(idx, color.Dim(map(values[3], 0, 100, 0, 255)));
  }
  rgb_keys.Show();
}

void rotateColors(std::vector<String>& colors) {
  if (colors.size() < 2) return;

  String first = colors[0];
  for (size_t i = 1; i < colors.size(); i++) {
    colors[i - 1] = colors[i];
  }
  colors.back() = first;
}

// Handlers
void handlePacket(const ParsedPacket &pkt) {
  Serial.printf("RX <- Opcode: 0x%02X, Length: %d\n", pkt.opcode, pkt.length);

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
        break;
      }

      uint8_t profileIndex = pkt.payload[0];
      uint8_t nameLength = pkt.payload[1];

      if (pkt.length < 2 + nameLength) {
        Serial.println("Error: CHANGE_PROFILE packet incomplete");
        break;
      }

      // Extract profile name
      String profileName = "";
      for (int i = 0; i < nameLength; i++) {
        profileName += (char)pkt.payload[2 + i];
      }

      // Store profile name
      if (profileIndex > 0 && profileIndex <= MAX_PROFILES) {
        int idx = profileIndex - 1;  // Convert to 0-based index
        profileNames[idx] = profileName;

        // Update profile count
        if (idx >= profileCount) {
          profileCount = idx + 1;
        }
        Serial.printf("Stored profile %d: '%s'\n", profileIndex, profileName.c_str());

        // Apply the profile if it's being set as current
        if (idx < 0 || idx >= profileCount) {
          Serial.printf("Invalid profile index: %d (max: %d)\n", idx, profileCount - 1);
          return;
        }
        currentProfile = idx;
        oledUpdate();
        Serial.printf("Applied CHANGE_PROFILE from PC -> %d (%s)\n", idx, profileNames[idx].c_str());
      } else {
        Serial.printf("Error: Invalid profile index %d\n", profileIndex);
      }
      break;
    }

    case OP_SYNC_PROFILES: {
      // Payload: count(1B) + [index(1B) + name_len(1B) + name]*count
      if (pkt.length < 1) {
        Serial.println("Error: SYNC_PROFILES packet too short");
        break;
      }

      uint8_t count = pkt.payload[0];
      Serial.printf("Syncing %d profiles\n", count);

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

        // Store profile name
        if (profileIndex > 0 && profileIndex <= MAX_PROFILES) {
          int idx = profileIndex - 1;
          profileNames[idx] = name;

          if (idx >= profileCount) {
            profileCount = idx + 1;
          }

          Serial.printf("Synced profile %d: '%s'\n", profileIndex, name.c_str());
        }
      }

      // Update display with current profile
      oledUpdate();
      break;
    }

    case OP_SET_RGB_KEY: {
      // Payload: key_index(1B) + R(1B) + G(1B) + B(1B) + W(1B)
      if (pkt.length != 5) {
        Serial.println("Error: SET_RGB_KEY invalid length");
        break;
      }

      uint8_t keyIndex = pkt.payload[0];
      uint8_t r = pkt.payload[1];
      uint8_t g = pkt.payload[2];
      uint8_t b = pkt.payload[3];
      uint8_t w = pkt.payload[4];

      // Validate indices
      if (keyIndex >= 16 || keyIndex >= rgbColors.size()) {
        Serial.printf("Error: Invalid key index %d\n", keyIndex);
        break;
      }

      // Update the color for this key
      rgbColors[keyIndex] = String(r) + "," + String(g) + "," + String(b) + "," + String(w);

      Serial.printf("Set key %d to RGBW(%d,%d,%d,%d)\n", keyIndex, r, g, b, w);

      // Update the LED immediately
      rgbUpdateColors(rgbColors, keyIndex);
      break;
    }

    case OP_SET_ALL_RGB_KEYS: {
      // Payload: 16 x RGBW (64 bytes total)
      if (pkt.length != 64) {
        Serial.printf("Error: SET_ALL_RGB_KEYS invalid length (expected 64, got %d)\n", pkt.length);
        break;
      }

      Serial.println("Setting all 16 RGB keys");

      // Update all 16 keys
      for (int i = 0; i < 16 && i < rgbColors.size(); i++) {
        uint8_t r = pkt.payload[i * 4];
        uint8_t g = pkt.payload[i * 4 + 1];
        uint8_t b = pkt.payload[i * 4 + 2];
        uint8_t w = pkt.payload[i * 4 + 3];

        // Store as string in format "R,G,B,W"
        rgbColors[i] = String(r) + "," + String(g) + "," + String(b) + "," + String(w);
      }

      // Update all LEDs at once
      rgbUpdateColors(rgbColors);
      Serial.println("All RGB keys updated");
      break;
    }

    case OP_LOCK_DEVICE: {
      // Payload: lock_flag(1B) - 0x01=lock, 0x00=unlock
      if (pkt.length != 1) {
        Serial.println("Error: LOCK_DEVICE invalid length");
        break;
      }

      uint8_t lockFlag = pkt.payload[0];

      if (lockFlag == 0x01) {
        workstationLocked = true;
        display->setBrightness(50);
        oledUpdateLockedStatus();
        Serial.println("Device LOCKED");
      } else if (lockFlag == 0x00) {
        workstationLocked = false;
        display->setBrightness(100);
        oledUpdate();
        Serial.println("Device UNLOCKED");
      } else {
        Serial.printf("Error: Invalid lock flag 0x%02X\n", lockFlag);
      }
      break;
    }

    default:
      Serial.printf("Unknown opcode: 0x%02X\n", pkt.opcode);
      break;
  }
}

void handleProfileChange() {
  Serial.printf("Profile changed to: %d (%s)\n", currentProfile, profileNames[currentProfile].c_str());
  oledUpdate();

  // Send profile change notification if connected
  if (deviceConnected) {
    Serial.printf("Sending profile change notification: %d\n", currentProfile);
    sendProfileChanged(currentProfile);
  } else {
    Serial.println("Device not connected - skipping profile notification");
  }
}

// BLE Callbacks with improved connection handling
class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) override {
    deviceConnected = true;
    connectionStartTime = millis();
    lastPingTime = millis();
    Serial.println("BLE Connected");

    #ifdef USE_BATTERY
    last_read_bat = 0;  // force batteryLoop() to fire on next iteration so the host gets an immediate reading
    #endif
  }

  void onDisconnect(BLEServer* pServer) override {
    deviceConnected = false;
    oldDeviceConnected = true;
    Serial.println("BLE Disconnected - Resetting to default state");

    // Reset to default state
    currentProfile = 0;
    profileCount = 1;

    // Clear all profile names and reset to default
    for (int i = 0; i < MAX_PROFILES; i++) {
      profileNames[i] = (i == 0) ? "Default" : "";
    }

    // Reset RGB colors to default
    rgbColors = defaultRgbColors;
    rgbUpdateColors(rgbColors);

    // Update OLED display
    oledUpdate();

    Serial.println("Reset complete - back to default profile");

    // Configure advertising with better parameters
    // Note: delay for BLE stack cleanup is handled in loop() via oldDeviceConnected guard
    BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
    pAdvertising->addServiceUUID("4FAFC201-1FB5-459E-8FCC-C5C9C331914B");
    pAdvertising->setScanResponse(false);
    pAdvertising->setMinPreferred(0x0);
    pAdvertising->setMinPreferred(0x1F);

    pServer->startAdvertising();
    Serial.println("Restarted advertising");
  }
};

class RxCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* pCharacteristic) override {
    std::string rx = pCharacteristic->getValue();
    if (rx.empty()) return;

    Serial.printf("BLE RX: %d bytes - ", rx.length());
    // Print first 8 bytes for quick inspection
    for (int i = 0; i < min((int)rx.length(), 8); i++) {
        Serial.printf("%02X ", (uint8_t)rx[i]);
    }
    Serial.println();

    ParsedPacket pkt;
    int packetCount = 0;

    for (uint8_t b : rx) {
        if (parser.feed(b, pkt)) {
            packetCount++;
            Serial.printf("Parsed packet #%d\n", packetCount);
            handlePacket(pkt);
        }
    }

    if (packetCount == 0) {
        Serial.println("Warning: No complete packets parsed from received data");
    } else {
        Serial.printf("Successfully parsed %d packet(s)\n", packetCount);
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
    Serial.println("Workstation Locked - no actions allowed");
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

void enterOtaMode() {
  Serial.println("Entering OTA mode");
  display->clear();
  display->setFont(ArialMT_Plain_10);
  display->drawString(16, 28, "Starting OTA...");
  display->display();
  delay(300);

  // Deinit BLE to free the shared radio for WiFi.
  // The BT controller needs ~500ms to fully release before WiFi can start.
  BLEDevice::deinit(true);
  delay(500);

  otaManager = new OtaManager(display);
  otaManager->begin(OTA_WIFI_SSID, OTA_WIFI_PASSWORD, OTA_PASSWORD, OTA_HOSTNAME);
  otaActive = true;  // always succeeds: AP fallback guarantees a network is up
}

void openMenu() {
  Serial.println("Opening settings menu");
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

void setup() {
  // Misc
  Serial.begin(115200);
  Serial.println("BLEDeck Firmware Starting...");

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

  // Set BLE power to maximum for better range
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_ADV, ESP_PWR_LVL_P9);
  //esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_SCAN, ESP_PWR_LVL_P9);

  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new ServerCallbacks());

  BLEService *service = pServer->createService("4FAFC201-1FB5-459E-8FCC-C5C9C331914B");

  pTxCharacteristic = service->createCharacteristic(
    "BEB5483E-36E1-4688-B7F5-EA07361B26A8",
    BLECharacteristic::PROPERTY_NOTIFY);
  pTxCharacteristic->addDescriptor(new BLE2902());

  BLECharacteristic *rx = service->createCharacteristic(
    "EAB5483E-36E1-4688-B7F5-EA07361B26A9",
    BLECharacteristic::PROPERTY_WRITE);
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

  // RGB
  rgbUpdateColors(rgbColors);

  #ifdef USE_BATTERY
  // Battery
  analogSetPinAttenuation(BAT_PIN, ADC_11db); // 0.1-3.1V range
  #endif

  Serial.println("Firmware ready - Advertising started");
  lastPingTime = millis();
}

void loop() {
  // Always update buttons so menu and long-press work regardless of BLE state
  btn_encoder_con.update();
  btn_encoder_back.update();
  btn_encoder_push.update();

  // OTA mode: hand off entirely to OTA manager
  if (otaActive) {
    // BACK cancels OTA — but never interrupt an in-progress upload
    if (btn_encoder_back.pressed() && !otaManager->isUpdating()) {
      Serial.println("OTA cancelled by user");
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
      Serial.println("OTA timeout - restarting");
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
    Serial.println("Connection cleanup completed");
  }

  // Debug: Log connection status changes
  static bool lastConnectedState = false;
  if (deviceConnected != lastConnectedState) {
    Serial.printf("Connection state changed: %s\n", deviceConnected ? "CONNECTED" : "DISCONNECTED");
    lastConnectedState = deviceConnected;
  }

  // Connection timeout check (optional - disconnect if no activity for too long)
  if (deviceConnected && (millis() - lastPingTime > 120000)) { // 2 minutes
    Serial.println("Connection timeout - no ping received");
    pServer->disconnect(pServer->getConnId());
  }

  if (deviceConnected) {
    if (btn_encoder_con.pressed()){
      Serial.println("CON PRESSED");
      sendButtonPressed("CON");
    }

    if (btn_encoder_back.pressed()){
      Serial.println("BACK PRESSED");
      sendButtonPressed("BACK");
    }

    // Short PUSH release sends event; long press was already handled above
    if (btn_encoder_push.released() &&
        btn_encoder_push.previousDuration() <= MENU_LONG_PRESS_MS) {
      Serial.println("PUSH PRESSED");
      sendButtonPressed("PUSH");
    }

    // Read keypad input
    char key = keypad->getKey();
    if (key && !workstationLocked) {
      Serial.println(key);
      sendKeyPressed(key);
    }

    // Perform encoder action
    if (turnedRightFlag) {
	    turnedRightFlag = false;
      Serial.println( "Right ->" );
      currentProfile++;
      if (currentProfile >= profileCount) {
        currentProfile = 0;  // Wrap to first profile
      }
      handleProfileChange();
    } else if( turnedLeftFlag ) {
	    turnedLeftFlag = false;
      Serial.println( "<- Left" );
      currentProfile--;
      if (currentProfile < 0) {
        currentProfile = profileCount - 1;  // Wrap to last profile
      }
      handleProfileChange();
    }
  } else {
    // Play idle RGB animation when not connected
    if (millis() - lastColorShift >= 200) {   // 200 ms passed
      lastColorShift = millis();
      rotateColors(rgbColors);
      rgbUpdateColors(rgbColors);
    }
  }

  #ifdef USE_BATTERY
  // Update adc reading
  batteryLoop();
  #endif

  // Small delay to prevent overwhelming the BLE stack
  delay(10);
}
