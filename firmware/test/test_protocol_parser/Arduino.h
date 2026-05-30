// Host-side shim for <Arduino.h>. The protocol parser only needs uint8_t /
// uint16_t / memcpy / sizeof. PlatformIO's native test runner adds this
// directory to the include path, so `#include <Arduino.h>` in
// firmware/src/protocolparser.h resolves to this empty header on the host
// while the real Arduino.h is used on the ESP32.
#pragma once
#include <stdint.h>
#include <string.h>
