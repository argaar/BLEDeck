#pragma once
#include <Arduino.h>

// ─── BLEDeck Binary Protocol ────────────────────────────────────────────────
//
// Frame format:  START(1) | OPCODE(1) | LENGTH_H(1) | LENGTH_L(1) | PAYLOAD(N)
//   START  = 0xAA
//   LENGTH = uint16 big-endian, byte count of PAYLOAD only
//
// PC → Device (commands)
//   0x01  KEEP_ALIVE         payload: (none)
//   0x02  CHANGE_PROFILE     payload: index(1) + name_len(1) + name(N)
//   0x03  SYNC_PROFILES      payload: count(1) + [index(1)+name_len(1)+name(N)]*count
//   0x04  SET_RGB_KEY        payload: key_index(1) + R(1) + G(1) + B(1) + W%(1)
//   0x05  SET_ALL_RGB_KEYS   payload: 16 × [R(1)+G(1)+B(1)+W%(1)]  = 64 bytes
//   0x06  LOCK_DEVICE        payload: flag(1)  0x01=lock 0x00=unlock
//   0x07  HELLO              payload: protocol_version(1) + app_version_len(1) + app_version(N)
//
// Device → PC (events)
//   0x81  KEEP_ALIVE_REPLY   payload: (none)
//   0x82  PROFILE_CHANGED    payload: profile_index(1)  0-based
//   0x83  BUTTON_PRESSED     payload: profile_index(1) + name_len(1) + name(N)
//   0x84  KEY_PRESSED        payload: profile_index(1) + key_char(1)
//   0x85  BATTERY_STATUS     payload: percent(1)  0-100 = %, 0xFF = no battery
//   0x86  DEVICE_TELEMETRY   payload: protocol_version(1) + firmware_version_len(1) + firmware_version(N)
//                                     + uptime_ms_be(4) + reset_reason(1) + free_heap_be(4)
//                                     + ble_error_count_be(2)
//
// Protocol version: incremented whenever wire-format changes. Bumping
// PROTOCOL_VERSION requires the Windows app to handle the version-mismatch
// path (see app HELLO/DEVICE_TELEMETRY handler) — never bump only one side.
//
// Profile limits: firmware tracks at most MAX_PROFILES = 10 profiles.
// CHANGE_PROFILE / SYNC_PROFILES indices > 10 are silently dropped by the device.
// ────────────────────────────────────────────────────────────────────────────

#define PROTOCOL_VERSION 1
#define START_BYTE       0xAA
#define MAX_PAYLOAD_LEN  256   // parser hard limit; matches MAX_BLE_PAYLOAD_LEN

// SYNC_PROFILES parses (nameLen, offset) where nameLen is uint8_t and offset
// walks payload[]. Keeping MAX_PAYLOAD_LEN <= 65535 ensures `offset + nameLen`
// computed in uint16_t cannot overflow during the bounds check, even if a
// future payload limit is raised. Catch any future relaxation that would
// break the assumption.
static_assert(MAX_PAYLOAD_LEN <= 65535,
              "MAX_PAYLOAD_LEN must fit uint16_t bounds check in SYNC_PROFILES");

enum Opcode {
    // PC → Device
    OP_KEEP_ALIVE       = 0x01,
    OP_CHANGE_PROFILE   = 0x02,
    OP_SYNC_PROFILES    = 0x03,
    OP_SET_RGB_KEY      = 0x04,
    OP_SET_ALL_RGB_KEYS = 0x05,
    OP_LOCK_DEVICE      = 0x06,
    OP_HELLO            = 0x07,
    // Device → PC
    OP_KEEP_ALIVE_REPLY = 0x81,
    OP_PROFILE_CHANGED  = 0x82,
    OP_BUTTON_PRESSED   = 0x83,
    OP_KEY_PRESSED      = 0x84,
    OP_BATTERY_STATUS   = 0x85,
    OP_DEVICE_TELEMETRY = 0x86,
};

struct ParsedPacket {
    uint8_t  opcode;
    uint16_t length;
    uint8_t  payload[MAX_PAYLOAD_LEN];
};

class ProtocolParser {
public:
    ProtocolParser() { reset(); }

    bool feed(uint8_t byte, ParsedPacket &out) {
        switch (state) {

        case WAIT_START:
            if (byte == START_BYTE) {
                state = READ_OPCODE;
            }
            break;

        case READ_OPCODE:
            opcode = byte;
            state = READ_LEN_H;
            break;

        case READ_LEN_H:
            length = byte << 8;
            state = READ_LEN_L;
            break;

        case READ_LEN_L:
            length |= byte;
            index = 0;

            // Drop packets that exceed the internal buffer (both buffers are 256 bytes)
            if (length > sizeof(payload)) {
                reset();
                break;
            }

            // Handle zero-length payload immediately
            if (length == 0) {
                out.opcode = opcode;
                out.length = 0;
                reset();
                return true;
            }

            state = READ_PAYLOAD;
            break;

        case READ_PAYLOAD:
            payload[index++] = byte;
            if (index >= length) {
                // full packet received
                out.opcode = opcode;
                out.length = length;
                memcpy(out.payload, payload, length);
                reset();
                return true;
            }
            break;
        }
        return false;
    }

private:
    enum State {
        WAIT_START,
        READ_OPCODE,
        READ_LEN_H,
        READ_LEN_L,
        READ_PAYLOAD
    } state;

    uint8_t  opcode;
    uint16_t length;
    uint16_t index;
    uint8_t  payload[MAX_PAYLOAD_LEN];

    void reset() {
        state = WAIT_START;
        index = 0;
    }
};
