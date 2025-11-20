#pragma once
#include <Arduino.h>

#define START_BYTE 0xAA

enum Opcode {
    OP_KEEP_ALIVE       = 0x01,
    OP_CHANGE_PROFILE   = 0x02,
    OP_SYNC_PROFILES    = 0x03,
    OP_SET_RGB_KEY      = 0x04,
    OP_SET_ALL_RGB_KEYS = 0x05,
    OP_LOCK_DEVICE      = 0x06,
    OP_KEEP_ALIVE_REPLY = 0x81,
    OP_PROFILE_CHANGED  = 0x82,
    OP_BUTTON_PRESSED   = 0x83,
    OP_KEY_PRESSED      = 0x84
};

struct ParsedPacket {
    uint8_t opcode;
    uint16_t length;
    uint8_t payload[256];
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

    uint8_t opcode;
    uint16_t length;
    uint16_t index;
    uint8_t payload[256];

    void reset() {
        state = WAIT_START;
        index = 0;
    }
};
