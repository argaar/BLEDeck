"""Tests for simulator/fake_bleak_client.py"""
import asyncio

from simulator.fake_bleak_client import FakeBleakClient, FakeBleakScanner
from simulator.device_state import DeviceState

_TX_UUID = "BEB5483E-36E1-4688-B7F5-EA07361B26A8"
_RX_UUID = "EAB5483E-36E1-4688-B7F5-EA07361B26A9"


def run(coro):
    return asyncio.run(coro)


# ─── FakeBleakScanner ──────────────────────────────────────────────────────────

def test_scanner_returns_bledeck():
    devices = run(FakeBleakScanner.discover(timeout=0.1))
    assert len(devices) == 1
    assert devices[0].name == "BLEDeck"


# ─── connect / disconnect ──────────────────────────────────────────────────────

def test_connect_sets_connected():
    async def _test():
        client = FakeBleakClient("00:SIM")
        assert not client.is_connected
        await client.connect()
        assert client.is_connected
    run(_test())


def test_disconnect_clears_connected():
    async def _test():
        client = FakeBleakClient("00:SIM")
        await client.connect()
        await client.disconnect()
        assert not client.is_connected
    run(_test())


def test_disconnected_callback_called():
    async def _test():
        called_with = []
        client = FakeBleakClient("00:SIM", disconnected_callback=called_with.append)
        await client.connect()
        await client.disconnect()
        assert called_with == [client]
    run(_test())


# ─── notify callback ───────────────────────────────────────────────────────────

def test_start_notify_stores_callback():
    async def _test():
        client = FakeBleakClient("00:SIM")
        received = []
        await client.start_notify(_TX_UUID, lambda s, d: received.append(bytes(d)))
        await client.push_event(b"\xAA\x81\x00\x00")
        assert received == [b"\xAA\x81\x00\x00"]
    run(_test())


def test_push_event_without_notify_does_not_raise():
    async def _test():
        client = FakeBleakClient("00:SIM")
        await client.connect()
        await client.push_event(b"\xAA\x85\x00\x01\x50")
    run(_test())


# ─── write_gatt_char → KEEP_ALIVE_REPLY ───────────────────────────────────────

def test_keep_alive_write_triggers_reply():
    from ble_protocol import BLEPacket, OP_KEEP_ALIVE, OP_KEEP_ALIVE_REPLY

    async def _test():
        client = FakeBleakClient("00:SIM")
        await client.connect()

        received: list[bytes] = []
        await client.start_notify(_TX_UUID, lambda s, d: received.append(bytes(d)))

        packet = BLEPacket.build(OP_KEEP_ALIVE)
        await client.write_gatt_char(_RX_UUID, packet)

        assert len(received) == 1
        op, _ = BLEPacket.parse(received[0])
        assert op == OP_KEEP_ALIVE_REPLY

    run(_test())


# ─── stop_notify ───────────────────────────────────────────────────────────────

def test_stop_notify_removes_callback():
    async def _test():
        client = FakeBleakClient("00:SIM")
        received = []
        await client.start_notify(_TX_UUID, lambda s, d: received.append(d))
        await client.stop_notify(_TX_UUID)
        await client.push_event(b"\xAA\x81\x00\x00")
        assert received == []
    run(_test())
