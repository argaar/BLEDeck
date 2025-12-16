#ifndef CONFIGURATION_H
#define CONFIGURATION_H

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
#define RGB_NUM                 1

// Power Management
#define BAT_INTERVAL_S          (30 * 1000) 
#define BAT_R1                  15000.0         // top resistor (to VIN)
#define BAT_R2                  4300.0          // bottom resistor (to GND)
#define BAT_NUM_READ            5
#define BAT_MAX_V               5.0             // USB Voltage or Max Voltage of a 1s1p lipo cell
#define BAT_MIN_V               2.4             // Min voltage to operate the MCU
#define BAT_PIN                 GPIO_NUM_13

#endif // CONFIGURATION_H