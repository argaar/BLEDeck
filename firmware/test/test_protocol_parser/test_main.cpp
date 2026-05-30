// Native Unity tests for ProtocolParser. Built with platform = native.
// Run: `pio test -e native`
//
// A shim `Arduino.h` sits next to this file (test_protocol_parser/Arduino.h)
// so that the `#include <Arduino.h>` inside protocolparser.h resolves on the
// host. PlatformIO's native test runner adds the test directory to the
// include path. The parser itself only needs <stdint.h> / <string.h>
// symbols.
#include <stdint.h>
#include <string.h>
#include <unity.h>

#include "../../src/protocolparser.h"

static ProtocolParser p;
static ParsedPacket out;

void setUp(void) {
    p = ProtocolParser();
    memset(&out, 0, sizeof(out));
}

void tearDown(void) {}

// ---------------------------------------------------------------------------

void test_zero_length_packet(void) {
    const uint8_t bytes[] = {0xAA, 0x01, 0x00, 0x00};  // KEEP_ALIVE
    bool got = false;
    for (uint8_t b : bytes) got |= p.feed(b, out);
    TEST_ASSERT_TRUE(got);
    TEST_ASSERT_EQUAL_HEX8(0x01, out.opcode);
    TEST_ASSERT_EQUAL_UINT16(0, out.length);
}

void test_single_byte_payload(void) {
    const uint8_t bytes[] = {0xAA, 0x06, 0x00, 0x01, 0x01};  // LOCK_DEVICE lock=1
    bool got = false;
    for (uint8_t b : bytes) got |= p.feed(b, out);
    TEST_ASSERT_TRUE(got);
    TEST_ASSERT_EQUAL_HEX8(0x06, out.opcode);
    TEST_ASSERT_EQUAL_UINT16(1, out.length);
    TEST_ASSERT_EQUAL_HEX8(0x01, out.payload[0]);
}

void test_garbage_bytes_resync_on_start(void) {
    const uint8_t garbage[] = {0xFF, 0xAB, 0x12, 0x33};
    for (uint8_t b : garbage) {
        bool got = p.feed(b, out);
        TEST_ASSERT_FALSE(got);
    }
    // Now feed a complete valid packet — parser must accept it cleanly.
    const uint8_t good[] = {0xAA, 0x01, 0x00, 0x00};
    bool got = false;
    for (uint8_t b : good) got |= p.feed(b, out);
    TEST_ASSERT_TRUE(got);
    TEST_ASSERT_EQUAL_HEX8(0x01, out.opcode);
}

void test_oversize_packet_dropped(void) {
    // Declare length = 0xFFFF, well above MAX_PAYLOAD_LEN (256). Parser must
    // drop the frame and return to WAIT_START without ever returning true.
    const uint8_t hdr[] = {0xAA, 0x07, 0xFF, 0xFF};
    for (uint8_t b : hdr) {
        TEST_ASSERT_FALSE(p.feed(b, out));
    }
    // After the drop, a fresh valid packet must work.
    const uint8_t good[] = {0xAA, 0x06, 0x00, 0x01, 0x00};
    bool got = false;
    for (uint8_t b : good) got |= p.feed(b, out);
    TEST_ASSERT_TRUE(got);
}

void test_multi_byte_payload(void) {
    // CHANGE_PROFILE: idx=1, name_len=4, "Test"
    const uint8_t bytes[] = {
        0xAA, 0x02, 0x00, 0x06,
        0x01, 0x04, 'T', 'e', 's', 't',
    };
    bool got = false;
    for (uint8_t b : bytes) got |= p.feed(b, out);
    TEST_ASSERT_TRUE(got);
    TEST_ASSERT_EQUAL_HEX8(0x02, out.opcode);
    TEST_ASSERT_EQUAL_UINT16(6, out.length);
    TEST_ASSERT_EQUAL_HEX8(0x01, out.payload[0]);
    TEST_ASSERT_EQUAL_HEX8(0x04, out.payload[1]);
    TEST_ASSERT_EQUAL_HEX8('T', out.payload[2]);
}

void test_payload_at_max_size(void) {
    // length = MAX_PAYLOAD_LEN. Verify parser accepts the edge case.
    uint8_t hdr[4] = {0xAA, 0x05, (uint8_t)(MAX_PAYLOAD_LEN >> 8),
                      (uint8_t)(MAX_PAYLOAD_LEN & 0xFF)};
    for (uint8_t b : hdr) TEST_ASSERT_FALSE(p.feed(b, out));
    bool got = false;
    for (int i = 0; i < MAX_PAYLOAD_LEN; ++i) {
        got |= p.feed((uint8_t)(i & 0xFF), out);
    }
    TEST_ASSERT_TRUE(got);
    TEST_ASSERT_EQUAL_UINT16(MAX_PAYLOAD_LEN, out.length);
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_zero_length_packet);
    RUN_TEST(test_single_byte_payload);
    RUN_TEST(test_garbage_bytes_resync_on_start);
    RUN_TEST(test_oversize_packet_dropped);
    RUN_TEST(test_multi_byte_payload);
    RUN_TEST(test_payload_at_max_size);
    return UNITY_END();
}
