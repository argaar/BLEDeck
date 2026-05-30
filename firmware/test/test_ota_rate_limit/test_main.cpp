// Native Unity tests for OtaRateLimiter. Built with platform = native.
// Run: `pio test -e native`
//
// The struct is header-only and isolated from Arduino / WiFi includes by the
// `#ifndef UNIT_TEST` guard in ota_manager.h, so we can include the header
// directly on the host with no shim.
#include <stdint.h>
#include <unity.h>
#include "../../src/ota_manager.h"

static OtaRateLimiter rl;

void setUp(void) { rl = OtaRateLimiter(); }
void tearDown(void) {}

// ---------------------------------------------------------------------------

void test_no_lockout_initially(void) {
    TEST_ASSERT_FALSE(rl.isLockedOut(0));
    TEST_ASSERT_FALSE(rl.isLockedOut(1000000));
}

void test_lockout_after_5_failures_within_window(void) {
    uint32_t t = 1000;
    for (int i = 0; i < 5; ++i) {
        rl.recordFailure(t);
        t += 10000;  // 10 s apart, total 40 s between first and last
    }
    TEST_ASSERT_TRUE(rl.isLockedOut(t));
}

void test_no_lockout_when_failures_spread(void) {
    uint32_t t = 1;  // start at 1 so the initial zero slot stays "empty"
    for (int i = 0; i < 5; ++i) {
        rl.recordFailure(t);
        t += 20000;  // 20 s apart, span 80 s — oldest stamp is outside window
    }
    TEST_ASSERT_FALSE(rl.isLockedOut(t));
}

void test_lockout_clears_after_5_minutes(void) {
    uint32_t t = 1000;
    for (int i = 0; i < 5; ++i) { rl.recordFailure(t); t += 1000; }
    TEST_ASSERT_TRUE(rl.isLockedOut(t));
    t += 5 * 60 * 1000 + 1;  // past the 5-minute lockout
    TEST_ASSERT_FALSE(rl.isLockedOut(t));
}

void test_failures_after_lockout_still_record(void) {
    // Even during a lockout, recordFailure should keep running through the
    // ring and not crash. After 10 rapid failures we are still in lockout.
    uint32_t t = 1000;
    for (int i = 0; i < 10; ++i) { rl.recordFailure(t); t += 1000; }
    TEST_ASSERT_TRUE(rl.isLockedOut(t));
}

int main(int, char**) {
    UNITY_BEGIN();
    RUN_TEST(test_no_lockout_initially);
    RUN_TEST(test_lockout_after_5_failures_within_window);
    RUN_TEST(test_no_lockout_when_failures_spread);
    RUN_TEST(test_lockout_clears_after_5_minutes);
    RUN_TEST(test_failures_after_lockout_still_record);
    return UNITY_END();
}
