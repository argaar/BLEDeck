"""Tests for ble_protocol module"""

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import ble_protocol


class TestBLEPacket:
    def test_build_minimal(self):
        packet = ble_protocol.BLEPacket.build(ble_protocol.OP_KEEP_ALIVE)
        assert packet == b'\xaa\x01\x00\x00'

    def test_build_with_payload(self):
        payload = b'\x01\x02\x03'
        packet = ble_protocol.BLEPacket.build(ble_protocol.OP_LOCK_DEVICE, payload)
        assert packet[:4] == b'\xaa\x06\x00\x03'
        assert packet[4:] == payload

    def test_parse_valid(self):
        raw = b'\xaa\x85\x00\x01\x64'
        opcode, payload = ble_protocol.BLEPacket.parse(raw)
        assert opcode == 0x85
        assert payload == b'\x64'

    def test_parse_too_short(self):
        import pytest
        with pytest.raises(ValueError, match="too short"):
            ble_protocol.BLEPacket.parse(b'\xaa\x01')

    def test_parse_bad_start_byte(self):
        import pytest
        with pytest.raises(ValueError, match="Invalid start byte"):
            ble_protocol.BLEPacket.parse(b'\xbb\x01\x00\x00')


class TestBuilders:
    def test_keep_alive(self):
        packet = ble_protocol.keep_alive()
        assert packet == b'\xaa\x01\x00\x00'

    def test_lock_device_lock(self):
        packet = ble_protocol.lock_device(True)
        assert packet == b'\xaa\x06\x00\x01\x01'

    def test_lock_device_unlock(self):
        packet = ble_protocol.lock_device(False)
        assert packet == b'\xaa\x06\x00\x01\x00'

    def test_change_profile(self):
        packet = ble_protocol.change_profile(1, "Test")
        assert packet[:4] == b'\xaa\x02\x00\x06'
        assert packet[4] == 1
        assert packet[5] == 4
        assert packet[6:] == b'Test'

    def test_sync_profiles(self):
        packet = ble_protocol.sync_profiles({1: "A", 2: "BB"})
        assert packet[:4] == b'\xaa\x03\x00\x08'
        assert packet[4] == 2
        # Profile 1
        assert packet[5] == 1
        assert packet[6] == 1
        assert packet[7:8] == b'A'
        # Profile 2
        assert packet[8] == 2
        assert packet[9] == 2
        assert packet[10:12] == b'BB'

    def test_set_rgb_key(self):
        packet = ble_protocol.set_rgb_key(5, 255, 128, 64, 50)
        assert packet == b'\xaa\x04\x00\x05\x05\xff\x80\x40\x32'

    def test_set_all_rgb_keys(self):
        rgbw_list = [(i, i, i, i) for i in range(16)]
        packet = ble_protocol.set_all_rgb_keys(rgbw_list)
        assert len(packet) == 4 + 64
        assert packet[0] == 0xAA
        assert packet[1] == 0x05
        assert packet[2] == 0x00
        assert packet[3] == 64

    def test_set_all_rgb_keys_wrong_count(self):
        import pytest
        with pytest.raises(ValueError, match="16 RGBW tuples"):
            ble_protocol.set_all_rgb_keys([(0, 0, 0, 0)])


class TestParsers:
    def test_parse_profile_changed(self):
        result = ble_protocol.parse_profile_changed(b'\x02')
        assert result == 2

    def test_parse_button_pressed(self):
        result = ble_protocol.parse_button_pressed(b'\x00\x04Test')
        assert result == (0, "Test")

    def test_parse_key_pressed(self):
        result = ble_protocol.parse_key_pressed(b'\x01\x41')
        assert result == (1, "A")

    def test_parse_battery_status_percent(self):
        result = ble_protocol.parse_battery_status(b'\x64')
        assert result == 100

    def test_parse_battery_status_usb(self):
        result = ble_protocol.parse_battery_status(b'\xff')
        assert result == 255

    def test_roundtrip_keep_alive(self):
        packet = ble_protocol.keep_alive()
        opcode, payload = ble_protocol.BLEPacket.parse(packet)
        assert opcode == ble_protocol.OP_KEEP_ALIVE
        assert payload == b''

    def test_roundtrip_battery_status(self):
        packet = ble_protocol.BLEPacket.build(0x85, b'\x64')
        opcode, payload = ble_protocol.BLEPacket.parse(packet)
        assert opcode == 0x85
        assert ble_protocol.parse_battery_status(payload) == 100


class TestParseColorString:
    def test_valid_color(self):
        result = ble_protocol.parse_color_string("100,150,200,70")
        assert result == (100, 150, 200, 70)

    def test_clamp_values(self):
        result = ble_protocol.parse_color_string("300,-1,128,150")
        assert result == (255, 0, 128, 100)

    def test_empty_parts_default_zero(self):
        result = ble_protocol.parse_color_string("10,,30,50")
        assert result == (10, 0, 30, 50)

    def test_whitespace_handling(self):
        result = ble_protocol.parse_color_string(" 10 , 20 , 30 , 40 ")
        assert result == (10, 20, 30, 40)

    def test_none_input(self):
        assert ble_protocol.parse_color_string(None) is None

    def test_empty_string(self):
        assert ble_protocol.parse_color_string("") is None

    def test_wrong_part_count(self):
        assert ble_protocol.parse_color_string("1,2,3") is None
        assert ble_protocol.parse_color_string("1,2,3,4,5") is None

    def test_non_numeric(self):
        assert ble_protocol.parse_color_string("a,b,c,d") is None


class TestOpcodeConstants:
    def test_command_opcodes(self):
        assert ble_protocol.OP_KEEP_ALIVE == 0x01
        assert ble_protocol.OP_CHANGE_PROFILE == 0x02
        assert ble_protocol.OP_SYNC_PROFILES == 0x03
        assert ble_protocol.OP_SET_RGB_KEY == 0x04
        assert ble_protocol.OP_SET_ALL_RGB_KEYS == 0x05
        assert ble_protocol.OP_LOCK_DEVICE == 0x06

    def test_event_opcodes(self):
        assert ble_protocol.OP_KEEP_ALIVE_REPLY == 0x81
        assert ble_protocol.OP_PROFILE_CHANGED == 0x82
        assert ble_protocol.OP_BUTTON_PRESSED == 0x83
        assert ble_protocol.OP_KEY_PRESSED == 0x84
        assert ble_protocol.OP_BATTERY_STATUS == 0x85


class TestParseColorStringEdgeCases:
    def test_whitespace_only(self):
        assert ble_protocol.parse_color_string("   ") is None

    def test_all_zeros(self):
        assert ble_protocol.parse_color_string("0,0,0,0") == (0, 0, 0, 0)

    def test_max_rgb_and_brightness(self):
        assert ble_protocol.parse_color_string("255,255,255,100") == (255, 255, 255, 100)

    def test_brightness_clamped_at_100(self):
        r, g, b, w = ble_protocol.parse_color_string("0,0,0,200")
        assert w == 100

    def test_rgb_clamped_at_255(self):
        r, g, b, w = ble_protocol.parse_color_string("999,999,999,50")
        assert r == 255 and g == 255 and b == 255

    def test_negative_rgb_clamped_to_zero(self):
        r, g, b, w = ble_protocol.parse_color_string("-10,-20,-30,50")
        assert r == 0 and g == 0 and b == 0

    def test_float_string_is_invalid(self):
        assert ble_protocol.parse_color_string("1.5,2.0,3.0,50") is None

    def test_empty_color_string_for_unassigned_key(self):
        # Empty string represents a key with no color — must return None, not crash
        assert ble_protocol.parse_color_string("") is None

    def test_none_for_unassigned_key(self):
        # None represents a key with no color — must return None, not crash
        assert ble_protocol.parse_color_string(None) is None


class TestSetRgbKeyBoundaries:
    def test_key_index_zero(self):
        packet = ble_protocol.set_rgb_key(0, 255, 0, 0, 100)
        opcode, payload = ble_protocol.BLEPacket.parse(packet)
        assert opcode == ble_protocol.OP_SET_RGB_KEY
        assert payload[0] == 0
        assert payload[1] == 255

    def test_key_index_fifteen(self):
        packet = ble_protocol.set_rgb_key(15, 0, 255, 0, 50)
        opcode, payload = ble_protocol.BLEPacket.parse(packet)
        assert payload[0] == 15
        assert payload[2] == 255

    def test_all_zeros(self):
        packet = ble_protocol.set_rgb_key(0, 0, 0, 0, 0)
        opcode, payload = ble_protocol.BLEPacket.parse(packet)
        assert payload == b'\x00\x00\x00\x00\x00'

    def test_payload_length(self):
        packet = ble_protocol.set_rgb_key(3, 10, 20, 30, 70)
        assert len(packet) == 4 + 5  # header + 5 payload bytes


class TestSetAllRgbKeysValues:
    def test_all_off(self):
        rgbw = [(0, 0, 0, 0)] * 16
        packet = ble_protocol.set_all_rgb_keys(rgbw)
        opcode, payload = ble_protocol.BLEPacket.parse(packet)
        assert opcode == ble_protocol.OP_SET_ALL_RGB_KEYS
        assert payload == bytes(64)

    def test_per_key_values_preserved(self):
        rgbw = [(i, i * 2 % 256, i * 3 % 256, i * 4 % 101) for i in range(16)]
        packet = ble_protocol.set_all_rgb_keys(rgbw)
        _, payload = ble_protocol.BLEPacket.parse(packet)
        for i in range(16):
            base = i * 4
            assert payload[base]     == rgbw[i][0]
            assert payload[base + 1] == rgbw[i][1]
            assert payload[base + 2] == rgbw[i][2]
            assert payload[base + 3] == rgbw[i][3]


class TestChangeProfileUtf8:
    def test_ascii_name_roundtrip(self):
        packet = ble_protocol.change_profile(2, "Work")
        opcode, payload = ble_protocol.BLEPacket.parse(packet)
        assert opcode == ble_protocol.OP_CHANGE_PROFILE
        assert payload[0] == 2
        name_len = payload[1]
        assert payload[2:2 + name_len].decode("utf-8") == "Work"

    def test_utf8_name(self):
        packet = ble_protocol.change_profile(1, "プロ🎹")
        opcode, payload = ble_protocol.BLEPacket.parse(packet)
        name_len = payload[1]
        assert payload[2:2 + name_len].decode("utf-8") == "プロ🎹"

    def test_empty_name(self):
        packet = ble_protocol.change_profile(1, "")
        opcode, payload = ble_protocol.BLEPacket.parse(packet)
        assert payload[1] == 0


class TestSyncProfilesEdgeCases:
    def test_empty_profiles(self):
        packet = ble_protocol.sync_profiles({})
        opcode, payload = ble_protocol.BLEPacket.parse(packet)
        assert opcode == ble_protocol.OP_SYNC_PROFILES
        assert payload[0] == 0

    def test_utf8_profile_name(self):
        packet = ble_protocol.sync_profiles({1: "Ñoño"})
        opcode, payload = ble_protocol.BLEPacket.parse(packet)
        assert payload[0] == 1
        name_len = payload[2]
        assert payload[3:3 + name_len].decode("utf-8") == "Ñoño"

    def test_count_field_matches_dict(self):
        packet = ble_protocol.sync_profiles({1: "A", 2: "B", 3: "C"})
        _, payload = ble_protocol.BLEPacket.parse(packet)
        assert payload[0] == 3


class TestParserLengthGuards:
    def test_profile_changed_empty_payload(self):
        import pytest
        with pytest.raises(ValueError, match="too short"):
            ble_protocol.parse_profile_changed(b'')

    def test_button_pressed_empty_payload(self):
        import pytest
        with pytest.raises(ValueError, match="too short"):
            ble_protocol.parse_button_pressed(b'')

    def test_button_pressed_one_byte(self):
        import pytest
        with pytest.raises(ValueError, match="too short"):
            ble_protocol.parse_button_pressed(b'\x00')

    def test_button_pressed_name_len_overruns(self):
        import pytest
        # name_len = 10 but only 3 bytes of name available → truncated
        with pytest.raises(ValueError, match="truncated"):
            ble_protocol.parse_button_pressed(b'\x00\x0aABC')

    def test_key_pressed_empty_payload(self):
        import pytest
        with pytest.raises(ValueError, match="too short"):
            ble_protocol.parse_key_pressed(b'')

    def test_key_pressed_one_byte(self):
        import pytest
        with pytest.raises(ValueError, match="too short"):
            ble_protocol.parse_key_pressed(b'\x00')

    def test_battery_status_empty_payload(self):
        import pytest
        with pytest.raises(ValueError, match="too short"):
            ble_protocol.parse_battery_status(b'')


class TestBLEPacketParse:
    def test_truncated_payload_rejected(self):
        # Packet declares 4 bytes but only 2 are present — parser now rejects.
        raw = b'\xaa\x85\x00\x04\x01\x02'
        with pytest.raises(ValueError, match="Truncated"):
            ble_protocol.BLEPacket.parse(raw)

    def test_payload_length_at_cap_accepted(self):
        # 256 byte payload (the cap) is allowed.
        payload = b'\xab' * ble_protocol.MAX_PAYLOAD_LEN
        raw = bytes([0xAA, 0x05, 0x01, 0x00]) + payload  # length = 0x0100 = 256
        opcode, parsed = ble_protocol.BLEPacket.parse(raw)
        assert opcode == 0x05
        assert parsed == payload

    def test_payload_length_above_cap_rejected(self):
        # length field = 257 → reject without inspecting buffer contents.
        raw = bytes([0xAA, 0x05, 0x01, 0x01]) + b'\x00' * 257
        with pytest.raises(ValueError, match="MAX_PAYLOAD_LEN"):
            ble_protocol.BLEPacket.parse(raw)

    def test_extra_trailing_bytes_ignored(self):
        raw = b'\xaa\x01\x00\x00\xff\xff\xff'
        opcode, payload = ble_protocol.BLEPacket.parse(raw)
        assert opcode == ble_protocol.OP_KEEP_ALIVE
        assert payload == b''

    def test_exact_four_bytes_no_payload(self):
        raw = b'\xaa\x01\x00\x00'
        opcode, payload = ble_protocol.BLEPacket.parse(raw)
        assert opcode == 0x01
        assert payload == b''


class TestHelloAndTelemetry:
    def test_hello_builder_known_bytes(self):
        # app_version "1.2.3" → header AA 07 00 07,
        # payload = protocol_version(1=0x01) + len(5=0x05) + "1.2.3"
        packet = ble_protocol.hello("1.2.3")
        assert packet == b'\xaa\x07\x00\x07\x01\x05' + b'1.2.3'

    def test_hello_constants_exposed(self):
        assert ble_protocol.OP_HELLO == 0x07
        assert ble_protocol.OP_DEVICE_TELEMETRY == 0x86
        assert ble_protocol.PROTOCOL_VERSION == 1

    def test_device_telemetry_parser_roundtrip(self):
        fw = "1.0.0"
        fw_bytes = fw.encode("utf-8")
        payload = bytes([1, len(fw_bytes)]) + fw_bytes
        payload += (123456).to_bytes(4, "big")   # uptime_ms
        payload += bytes([7])                    # reset_reason
        payload += (200000).to_bytes(4, "big")   # free_heap
        payload += (42).to_bytes(2, "big")       # ble_error_count

        result = ble_protocol.parse_device_telemetry(payload)
        assert result == {
            "protocol_version": 1,
            "firmware_version": "1.0.0",
            "uptime_ms": 123456,
            "reset_reason": 7,
            "free_heap": 200000,
            "ble_error_count": 42,
        }

    def test_device_telemetry_truncated_rejected(self):
        # Declares 5-byte firmware version but payload ends right after it,
        # missing uptime/reset/heap/errors.
        fw_bytes = b"1.0.0"
        truncated = bytes([1, len(fw_bytes)]) + fw_bytes
        with pytest.raises(ValueError, match="truncated"):
            ble_protocol.parse_device_telemetry(truncated)

    def test_device_telemetry_too_short_header(self):
        with pytest.raises(ValueError, match="too short"):
            ble_protocol.parse_device_telemetry(b'\x01')