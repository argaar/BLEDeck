#include "configuration.h"
#include <Keypad.h>
#include <ESP32RotaryEncoder.h>
#include <Bounce2.h>
#include <Wire.h>
#include "SSD1306Wire.h"
#include "OLEDDisplay.h"
#include <Preferences.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <images.h>

// Prefs
Preferences prefs;

// Profiles - can be updated from Windows app
int currentProfile = 0;
const int MAX_PROFILES = 10;  // Support up to 10 profiles
String profileNames[MAX_PROFILES] = {"Default"};  // Initialize first profile, rest will be set by app
int profileCount = 1;  // Track number of profiles received from app

// OLED
SSD1306Wire * display;

void updateOLED(int profile) {
  display->clear();
  char profile_string[40];
  snprintf(profile_string, sizeof(profile_string), "Profile: %s", profileNames[profile]);
  display->drawString(0, 0, profile_string);
  display->display();
  Serial.println(profile_string);
}

// BLE Connection Management
BLEServer* pServer;
BLECharacteristic* pTxCharacteristic;
bool deviceConnected = false;
bool oldDeviceConnected = false;
bool oledDimmed = false;
unsigned long lastPingTime = 0;
unsigned long connectionStartTime = 0;

// BLE Send Helpers
void sendNotify(const String &msg) {
  if (!deviceConnected) {
    Serial.println("Cannot send - device not connected");
    return;
  }
  
  if (!pTxCharacteristic) {
    Serial.println("Cannot send - characteristic not available");
    return;
  }
  
  try {
    String out;
    // For PROFILE: messages, don't prepend profile name (it's the profile index)
    if (msg.startsWith("PROFILE:") || msg.startsWith("ACK:")) {
      out = msg;
    } else {
      // For key presses and other messages, prepend current profile name
      out = profileNames[currentProfile] + ";" + msg;
    }
    
    pTxCharacteristic->setValue(out.c_str());
    pTxCharacteristic->notify();
    Serial.printf("TX -> %s\n", out.c_str());
  } catch (...) {
    Serial.println("Error sending notification");
    deviceConnected = false;
  }
}

void sendAckPing() {
  sendNotify("ACK:PING");
  lastPingTime = millis();
}

// BLE Functions
void applyProfileFromPC(int idx) {
  if (idx < 0 || idx >= profileCount) {
    Serial.printf("Invalid profile index: %d (max: %d)\n", idx, profileCount - 1);
    return;
  }
  currentProfile = idx;
  prefs.begin("bledeck", false);
  prefs.putInt("currentprofile", currentProfile);
  prefs.end();
  updateOLED(currentProfile);
  Serial.printf("Applied SET_PROFILE from PC -> %d (%s)\n", idx, profileNames[idx].c_str());
  sendNotify("ACK:SET_PROFILE:" + String(idx));
  sendNotify("PROFILE:" + String(idx));
}

// BLE Callbacks with improved connection handling
class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* pServer) override {
    deviceConnected = true;
    connectionStartTime = millis();
    lastPingTime = millis();
    Serial.println("BLE Connected");
    
    // Set connection parameters for better stability
    // Note: Connection parameter updates are handled automatically by ESP32
  }
  
  void onDisconnect(BLEServer* pServer) override {
    deviceConnected = false;
    oldDeviceConnected = true;
    Serial.println("BLE Disconnected");
    
    // Small delay before restarting advertising
    delay(500);
    
    // Configure advertising with better parameters
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
    
    String msg = String(rx.c_str());
    msg.trim();

    Serial.printf("RX <- %s\n", msg.c_str());

    // Reset ping timer on any received message
    lastPingTime = millis();

    if (msg.startsWith("SET_PROFILE:")) {
      int idx = msg.substring(12).toInt();
      applyProfileFromPC(idx);
    }
    else if (msg.startsWith("PROFILE_NAME:")) {
      int sep = msg.indexOf('|');
      if (sep > 0) {
        int colon = msg.indexOf(':');
        int idx = msg.substring(colon+1, sep).toInt();
        String name = msg.substring(sep+1);
        
        if (idx >= 0 && idx < MAX_PROFILES) {
          profileNames[idx] = name;
          // Update profile count to include this profile
          if (idx >= profileCount) {
            profileCount = idx + 1;
          }
          
          Serial.printf("Updated profile %d: '%s' (total profiles: %d)\n", idx, name.c_str(), profileCount);
          
          // Update OLED if this is the current profile
          if (idx == currentProfile) updateOLED(currentProfile);
          
          // Send acknowledgment
          sendNotify("ACK:PROFILE_NAME:" + String(idx));
        } else {
          Serial.printf("Invalid profile index: %d\n", idx);
        }
      }
    }
    else if (msg.startsWith("LOCKED:")) {
      String v = msg.substring(7);
      if (v == "1") {
        oledDimmed = true;
        display->setContrast(0);
      } else {
        oledDimmed = false;
        display->setContrast(100);
        updateOLED(currentProfile);
      }
    }
    else if (msg.startsWith("PING")) {
      sendAckPing();
    }
    else if (msg.startsWith("ACK:")) {
      // Client acknowledged our ping
      lastPingTime = millis();
    }
    else {
      Serial.printf("Unknown command: %s\n", msg.c_str());
    }
  }
};

// ENCODER
Bounce2::Button btn_encoder_con = Bounce2::Button();
Bounce2::Button btn_encoder_back = Bounce2::Button();
RotaryEncoder rotaryEncoder( DI_ENCODER_A, DI_ENCODER_B, -1 );

volatile bool turnedRightFlag = false;
volatile bool turnedLeftFlag = false;

void knobCallback( long value ) {
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
  {'F','B','7','3'},
  {'E','A','6','2'},
  {'D','9','5','1'},
  {'C','8','4','0'}
};

byte rowPins[4] = {ROW_PIN_1, ROW_PIN_2, ROW_PIN_3, ROW_PIN_4};
byte colPins[4] = {COL_PIN_1, COL_PIN_2, COL_PIN_3, COL_PIN_4};
Keypad* keypad;

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

  // BLE with improved configuration
  BLEDevice::init("BLEDeck");
  
  // Set BLE power to maximum for better range
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_ADV, ESP_PWR_LVL_P9);
  esp_ble_tx_power_set(ESP_BLE_PWR_TYPE_SCAN, ESP_PWR_LVL_P9);
  
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
  prefs.begin("bledeck", true);
  currentProfile = prefs.getInt("currentprofile", 0);
  prefs.end();
  updateOLED(currentProfile);

  Serial.println("Firmware ready - Advertising started");
  lastPingTime = millis();
}

void loop() {
  btn_encoder_con.update();
  btn_encoder_back.update();

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

  if (btn_encoder_con.pressed()){
    Serial.println("CON PRESSED");
    sendNotify("CON");
  }

  if (btn_encoder_back.pressed()){
    Serial.println("BACK PRESSED");
    sendNotify("BACK");
  }

  char key = keypad->getKey();
  if (key) {
    Serial.println(key);
    String key_s(key);
    sendNotify(key_s);
  }

  if (turnedRightFlag) {
	  turnedRightFlag = false;
    Serial.println( "Right ->" );
    currentProfile++;
    if (currentProfile >= profileCount) {
      currentProfile = 0;  // Wrap to first profile
    }
    
    Serial.printf("Profile changed to: %d (%s)\n", currentProfile, profileNames[currentProfile].c_str());
    updateOLED(currentProfile);
    
    // Send profile change notification if connected
    if (deviceConnected) {
      Serial.printf("Sending profile change notification: PROFILE:%d\n", currentProfile);
      sendNotify("PROFILE:" + String(currentProfile));
    } else {
      Serial.println("Device not connected - skipping profile notification");
    }
  } else if( turnedLeftFlag ) {
	  turnedLeftFlag = false;
    Serial.println( "<- Left" );
    currentProfile--;
    if (currentProfile < 0) {
      currentProfile = profileCount - 1;  // Wrap to last profile
    }
    
    Serial.printf("Profile changed to: %d (%s)\n", currentProfile, profileNames[currentProfile].c_str());
    updateOLED(currentProfile);
    
    // Send profile change notification if connected
    if (deviceConnected) {
      Serial.printf("Sending profile change notification: PROFILE:%d\n", currentProfile);
      sendNotify("PROFILE:" + String(currentProfile));
    } else {
      Serial.println("Device not connected - skipping profile notification");
    }
  }
  
  // Small delay to prevent overwhelming the BLE stack
  delay(10);
}