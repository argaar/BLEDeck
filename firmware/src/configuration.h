#ifndef CONFIGURATION_H
#define CONFIGURATION_H

// #define DEBUG_SERIAL  // Uncomment for verbose serial logging

// OLED
#define SCREEN_WIDTH            128
#define SCREEN_HEIGHT           64
#define I2C_SDA                 21
#define I2C_SCL                 22
#define SSD1306_ADDRESS         0x3C

// Encoder
#define DI_ENCODER_A            GPIO_NUM_35
#define DI_ENCODER_B            GPIO_NUM_34
#define DI_ENCODER_CON          GPIO_NUM_36
#define DI_ENCODER_BACK         GPIO_NUM_39
#define DI_ENCODER_PUSH         GPIO_NUM_27
#define BUTTON_DEBOUNCE_MS      50

// Keys
#define ROW_PIN_1               GPIO_NUM_32
#define ROW_PIN_2               GPIO_NUM_33
#define ROW_PIN_3               GPIO_NUM_25
#define ROW_PIN_4               GPIO_NUM_26
#define COL_PIN_1               GPIO_NUM_5
#define COL_PIN_2               GPIO_NUM_18
#define COL_PIN_3               GPIO_NUM_19
#define COL_PIN_4               GPIO_NUM_23

// RGB
#define RGB_PIN                 GPIO_NUM_14
#define RGB_NUM                 16

// BLE packet limits - must match ParsedPacket::payload size in protocolparser.h
#define MAX_BLE_PAYLOAD_LEN  256
#define MAX_BUTTON_NAME_LEN  32

// BLE connection health
// Drop connection if no KEEP_ALIVE received within this window. App pings
// every 10s, so 30s tolerates up to two consecutive missed pings.
#define BLE_PING_TIMEOUT_MS  30000UL

// OTA Update
#include "credentials.h"   // gitignored - copy credentials.h.example and fill in
#define OTA_HOSTNAME            "bledeck"
#define OTA_AP_SSID             "BLEDeck-OTA"   // AP fallback network name
#define OTA_AP_PASSWORD_LEN     12              // random AP password length
#define OTA_TIMEOUT_MS          300000UL    // 5 minutes
#define MENU_LONG_PRESS_MS      1500         // ms to hold PUSH to open menu

// Power Management
#define USE_BATTERY
#define BAT_INTERVAL_MS         (30 * 1000)     // Battery sample interval (milliseconds)
#ifdef CALIBRATE_BATTERY
#undef BAT_INTERVAL_MS
#define BAT_INTERVAL_MS         (5 * 1000)      // Faster sampling in calibration build (pio run -e calibrate)
#endif
// 1S LiPo divider on GPIO 13: PCB ships with R1=15k (top, to BAT+), R2=4.3k (bottom, to GND).
// Empirical calibration (best-fit through origin across two measurements):
//   adc=2427 mV → multimeter 3948 mV
//   adc=2505 mV → multimeter 4035 mV
// Best-fit effective Vbat/Vadc multiplier = 1.6185. The theoretical divider
// multiplier (R1+R2)/R2 = 4.488, so BAT_CALIBRATION ≈ 1.6185 / 4.488 = 0.3607.
// The over-read is likely caused by ADC2 behaviour on GPIO 13 combined with
// internal attenuation calibration; do not change the resistor constants to
// compensate — keep them matching the soldered board.
// Watch the `[BAT] adc=... vbat=... pct=...` serial line and compare vbat
// against a multimeter; tune BAT_CALIBRATION to match.
#define BAT_R1                  15000.0         // top resistor (to VIN)
#define BAT_R2                  4300.0          // bottom resistor (to GND)
#define BAT_CALIBRATION         0.3607          // empirical ADC correction (1.000 = no correction)
#define BAT_NUM_READ            5
#define BAT_MAX_V               4200            // Max voltage of a 1S LiPo cell (in mV)
#define BAT_MIN_V               3200            // Min useful voltage of a 1S LiPo cell (in mV); 3700 showed 0% at ~15% remaining
#define BAT_PIN                 GPIO_NUM_13

#endif // CONFIGURATION_H