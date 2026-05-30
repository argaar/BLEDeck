#include "ota_manager.h"
#include "configuration.h"
#include <ElegantOTA.h>
#include <WiFi.h>

// Migration guard: v1.2.2 renamed OTA_PASSWORD -> OTA_HTTP_PASSWORD in
// credentials.h.example. Fail loudly on stale credentials.h files so users
// see a clear action item instead of a cryptic undefined-symbol error
// elsewhere in the build.
#ifndef OTA_HTTP_PASSWORD
#error "credentials.h: rename OTA_PASSWORD to OTA_HTTP_PASSWORD (see firmware/src/credentials.h.example and CHANGELOG v1.2.2)"
#endif

OtaManager::OtaManager(SSD1306Wire* display)
  : display_(display), server_(new WebServer(80)),
    startTime_(0), lastApCheckMs_(0),
    apMode_(false), updating_(false), lastClientCount_(0),
    authLimiter_() {
  hostname_[0] = '\0';
  apPassword_[0] = '\0';
}

// ---------------------------------------------------------------------------
// Auth-failure rate-limit logic lives in the header-only OtaRateLimiter
// struct (ota_manager.h) so it can be exercised by host-side Unity tests
// without dragging in Arduino or WiFi headers. See
// test/test_ota_rate_limit/test_main.cpp.

OtaManager::~OtaManager() {
  delete server_;
}

// ---------------------------------------------------------------------------

void OtaManager::connectSta(const char* ssid, const char* password) {
  display_->clear();
  display_->setFont(ArialMT_Plain_10);
  display_->drawString(0, 0, "OTA Mode");
  display_->drawString(0, 14, "Connecting to WiFi...");
  display_->display();

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  unsigned long t = millis();
  uint8_t dots = 0;
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - t > 15000) return;   // timed out - caller checks status
    delay(400);
    dots = (dots % 3) + 1;
    char buf[28];
    snprintf(buf, sizeof(buf), "Connecting%.*s   ", dots, "...");
    display_->clear();
    display_->setFont(ArialMT_Plain_10);
    display_->drawString(0, 0, "OTA Mode");
    display_->drawString(0, 14, buf);
    display_->display();
  }
}

void OtaManager::startAp(const char* apPassword) {
  display_->clear();
  display_->setFont(ArialMT_Plain_10);
  display_->drawString(0, 0, "OTA Mode");
  display_->drawString(0, 14, "Starting AP...");
  display_->display();

  // Mode switch then softAP with delay between - fixes "ESP_XXXX" SSID bug
  WiFi.mode(WIFI_AP);
  delay(200);
  WiFi.softAP(OTA_AP_SSID, apPassword);
  delay(500);   // let beacon start broadcasting with the configured SSID

  Serial.printf("AP: %s @ %s\n", OTA_AP_SSID, WiFi.softAPIP().toString().c_str());
  apMode_ = true;
}

// ---------------------------------------------------------------------------

void OtaManager::begin(const char* ssid, const char* staPassword,
                       const char* apPassword, const char* httpPassword,
                       const char* hostname) {
  startTime_ = millis();
  strncpy(hostname_, hostname, sizeof(hostname_) - 1);
  hostname_[sizeof(hostname_) - 1] = '\0';
  strncpy(apPassword_, apPassword, sizeof(apPassword_) - 1);
  apPassword_[sizeof(apPassword_) - 1] = '\0';

  // Reset WiFi to a known-clean state
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  delay(100);

  // Try home WiFi first, fall back to AP
  connectSta(ssid, staPassword);
  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("STA failed (status=%d), switching to AP\n", WiFi.status());
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    delay(100);
    startAp(apPassword_);
  } else {
    apMode_ = false;
    Serial.printf("STA connected: %s\n", WiFi.localIP().toString().c_str());
  }

  // ElegantOTA - serve at http://<ip>/update
  // Empty username; httpPassword used for HTTP Basic auth on the upload page.
  // Distinct from apPassword_ to avoid credential reuse across two trust boundaries.
  ElegantOTA.begin(server_, "", httpPassword);

  ElegantOTA.onStart([this]() {
    updating_ = true;
    display_->clear();
    display_->setFont(ArialMT_Plain_16);
    display_->drawString(0, 0, "Uploading...");
    display_->drawRect(5, 30, 118, 14);
    display_->display();
    Serial.println("OTA upload started");
  });

  ElegantOTA.onProgress([this](size_t current, size_t total) {
    if (total == 0) return;
    int barWidth = (int)(118.0f * current / total);
    display_->clear();
    display_->setFont(ArialMT_Plain_16);
    display_->drawString(0, 0, "Uploading...");
    display_->drawRect(5, 30, 118, 14);
    if (barWidth > 0)
      display_->fillRect(5, 30, barWidth, 14);
    char pct[8];
    snprintf(pct, sizeof(pct), "%3d%%", (int)(100.0f * current / total));
    display_->setFont(ArialMT_Plain_10);
    display_->drawString(50, 46, pct);
    display_->display();
  });

  ElegantOTA.onEnd([this](bool success) {
    updating_ = false;
    display_->clear();
    display_->setFont(ArialMT_Plain_16);
    if (success) {
      display_->drawString(8, 20, "Done!");
      display_->setFont(ArialMT_Plain_10);
      display_->drawString(16, 42, "Restarting...");
    } else {
      display_->drawString(0, 20, "Upload failed");
      display_->setFont(ArialMT_Plain_10);
      display_->drawString(16, 42, "Try again");
    }
    display_->display();
    Serial.printf("OTA end, success=%d\n", success);
  });

  server_->begin();
  showReady();
}

// ---------------------------------------------------------------------------

void OtaManager::loop() {
  // Rate-limit gate: if we are inside the post-failure lockout window, drop
  // incoming HTTP traffic entirely (no handleClient → connections close).
  // TODO: ElegantOTA 3.1.7 does not expose an auth-failure callback. The
  // `_authenticate` checks live inside its private route handlers, so we have
  // no clean injection point to call `authLimiter_.recordFailure()` on each
  // 401. The counter / lockout infrastructure is wired and ready; when the
  // library grows an `onAuthFail` hook (or we self-host the route handlers)
  // call `authLimiter_.recordFailure(millis())` from there. Until then the
  // lockout only triggers if some future code path records failures
  // explicitly.
  if (authLimiter_.isLockedOut(millis())) {
    return;
  }
  server_->handleClient();
  ElegantOTA.loop();

  // Refresh AP client count on display when it changes
  if (apMode_ && !updating_) {
    if (millis() - lastApCheckMs_ > 1000) {
      lastApCheckMs_ = millis();
      uint8_t count = (uint8_t)WiFi.softAPgetStationNum();
      if (count != lastClientCount_) {
        lastClientCount_ = count;
        showReady();
      }
    }
  }
}

bool OtaManager::timedOut() const {
  return millis() - startTime_ > OTA_TIMEOUT_MS;
}

// ---------------------------------------------------------------------------

void OtaManager::showReady() {
  display_->clear();

  if (apMode_) {
    display_->setFont(ArialMT_Plain_10);
    display_->drawString(0, 0, "AP: " OTA_AP_SSID);
    char pwLine[24];
    snprintf(pwLine, sizeof(pwLine), "PW: %s", apPassword_);
    display_->drawString(0, 11, pwLine);
    display_->drawString(0, 22, WiFi.softAPIP().toString().c_str() + String("/update"));
    if (lastClientCount_ > 0) {
      char buf[28];
      snprintf(buf, sizeof(buf), "%d device(s) connected", (int)lastClientCount_);
      display_->drawString(0, 40, buf);
    } else {
      display_->drawString(0, 40, "No clients yet");
    }
  } else {
    display_->setFont(ArialMT_Plain_16);
    display_->drawString(0, 0, "OTA Ready");
    display_->setFont(ArialMT_Plain_10);
    display_->drawString(0, 20, WiFi.localIP().toString().c_str());
    char buf[44];
    snprintf(buf, sizeof(buf), "%s.local/update", hostname_);
    display_->drawString(0, 32, buf);
  }

  display_->setFont(ArialMT_Plain_10);
  display_->drawString(0, 54, "BACK=cancel  5min timeout");
  display_->display();
}
