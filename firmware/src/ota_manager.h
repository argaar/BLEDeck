#pragma once
#include <stdint.h>

// ─── OtaRateLimiter ────────────────────────────────────────────────────────
// Ring-buffer counter for failed HTTP-auth attempts. Five failures inside
// `kWindowMs` arm a `kLockoutMs` lockout, during which `isLockedOut()` stays
// true. Extracted as a standalone struct so it can be unit-tested on the
// host (no Arduino / WiFi dependency).
//
// Algorithm: timestamps are written into a 5-slot ring. After advancing the
// write index, the slot it now points to holds the OLDEST timestamp (the one
// about to be overwritten on the next call). If that oldest slot is non-zero
// and was recorded within the window, then by construction all five slots
// are within the window — trigger lockout.
// ───────────────────────────────────────────────────────────────────────────
struct OtaRateLimiter {
    static constexpr uint8_t  kWindowSize = 5;
    static constexpr uint32_t kWindowMs   = 60000;
    static constexpr uint32_t kLockoutMs  = 5 * 60000;

    uint32_t timestamps_[kWindowSize] = {0};
    uint8_t  idx_ = 0;
    uint32_t lockoutUntilMs_ = 0;

    void recordFailure(uint32_t now_ms) {
        timestamps_[idx_] = now_ms;
        idx_ = (idx_ + 1) % kWindowSize;
        uint32_t oldest = timestamps_[idx_];  // ring wrap = oldest slot
        if (oldest != 0 && (now_ms - oldest) <= kWindowMs) {
            lockoutUntilMs_ = now_ms + kLockoutMs;
        }
    }

    bool isLockedOut(uint32_t now_ms) const {
        return lockoutUntilMs_ != 0 && now_ms < lockoutUntilMs_;
    }
};

// On the host (UNIT_TEST native env) we stop here — the full OtaManager
// depends on Arduino / WiFi / OLED headers that do not exist off-target.
#ifndef UNIT_TEST

#include <Arduino.h>
#include "SSD1306Wire.h"
#include <WebServer.h>

class OtaManager {
public:
  explicit OtaManager(SSD1306Wire* display);
  ~OtaManager();

  // staPassword: home WiFi password (STA mode).
  // apPassword:  WPA2 password for fallback BLEDeck-OTA AP. Should be
  //              regenerated per-boot and displayed on the OLED so the
  //              AP credential never matches the HTTP auth credential.
  // httpPassword: HTTP Basic auth password for the /update page.
  void begin(const char* ssid, const char* staPassword,
             const char* apPassword, const char* httpPassword,
             const char* hostname);
  void loop();
  bool timedOut() const;
  bool isUpdating() const { return updating_; }

private:
  SSD1306Wire* display_;
  WebServer* server_;
  unsigned long startTime_;
  unsigned long lastApCheckMs_;
  char hostname_[33];
  char apPassword_[16];   // shown on OLED when in AP fallback mode
  bool apMode_;
  bool updating_;
  uint8_t lastClientCount_;

  OtaRateLimiter authLimiter_;

  void connectSta(const char* ssid, const char* password);
  void startAp(const char* apPassword);
  void showReady();
};

#endif // UNIT_TEST
