#pragma once
#include <Arduino.h>
#include "SSD1306Wire.h"
#include <WebServer.h>

class OtaManager {
public:
  explicit OtaManager(SSD1306Wire* display);
  ~OtaManager();

  void begin(const char* ssid, const char* password,
             const char* otaPassword, const char* hostname);
  void loop();
  bool timedOut() const;
  bool isUpdating() const { return updating_; }

private:
  SSD1306Wire* display_;
  WebServer* server_;
  unsigned long startTime_;
  unsigned long lastApCheckMs_;
  char hostname_[33];
  bool apMode_;
  bool updating_;
  uint8_t lastClientCount_;

  void connectSta(const char* ssid, const char* password);
  void startAp(const char* otaPassword);
  void showReady();
};
