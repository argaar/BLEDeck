"""
FakeBleakClient — in-process loopback for Mode A (BLEDECK_SIM=1).

Mimics the bleak.BleakClient API used by windows_app/main.py:
  connect() / disconnect() / is_connected
  start_notify(uuid, callback)
  write_gatt_char(uuid, data, response=False)

FakeBleakScanner.discover() returns a single fake BLEDeck device.
Call push_event(data) to inject a spontaneous Device→PC event packet.
"""
import asyncio
import logging
from typing import Callable

import simulator  # noqa: F401  trigger sys.path shim

logger = logging.getLogger(__name__)

_FAKE_ADDRESS = "00:00:00:00:00:SIM"


# ---------------------------------------------------------------------------
# Minimal GATT service/characteristic stubs — used by FakeBleakClient.services
# so the post-connect GATT verification in main.py passes in loopback mode.
# ---------------------------------------------------------------------------
class _FakeGATTChar:
    def __init__(self, uuid: str) -> None:
        self.uuid = uuid.lower()


class _FakeGATTService:
    def __init__(self) -> None:
        from ble_client import CHAR_TX_UUID, CHAR_RX_UUID
        self._chars: dict[str, _FakeGATTChar] = {
            CHAR_TX_UUID.lower(): _FakeGATTChar(CHAR_TX_UUID),
            CHAR_RX_UUID.lower(): _FakeGATTChar(CHAR_RX_UUID),
        }

    def get_characteristic(self, uuid: str) -> "_FakeGATTChar | None":
        return self._chars.get(str(uuid).lower())


class _FakeGATTServiceCollection:
    def __init__(self) -> None:
        from ble_client import SERVICE_UUID
        self._service_uuid = SERVICE_UUID.lower()
        self._svc = _FakeGATTService()

    def get_service(self, uuid: str) -> "_FakeGATTService | None":
        return self._svc if str(uuid).lower() == self._service_uuid else None


class FakeBleakScanner:
    @staticmethod
    async def discover(timeout: float = 5.0, **kwargs) -> list:
        await asyncio.sleep(0.05)
        return [_FakeDevice()]


class _FakeDevice:
    name = "BLEDeck"
    address = _FAKE_ADDRESS


class FakeBleakClient:
    def __init__(
        self,
        address: str,
        disconnected_callback: Callable | None = None,
        **kwargs,
    ) -> None:
        from simulator._context import get_state
        self._address = address
        self._disconnected_callback = disconnected_callback
        self._connected = False
        self._notify_callbacks: dict[str, Callable] = {}
        self._state = get_state()

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def address(self) -> str:
        return self._address

    @property
    def services(self) -> _FakeGATTServiceCollection:
        return _FakeGATTServiceCollection()

    async def connect(self, **kwargs) -> bool:
        from simulator._context import set_active_client
        self._connected = True
        set_active_client(self)
        logger.info("[SIM] Loopback connected")
        return True

    async def disconnect(self) -> bool:
        if self._connected:
            self._connected = False
            logger.info("[SIM] Loopback disconnected")
            if self._disconnected_callback:
                self._disconnected_callback(self)
        from simulator._context import set_active_client
        set_active_client(None)
        return True

    async def start_notify(self, uuid: str, callback: Callable, **kwargs) -> None:
        self._notify_callbacks[uuid.upper()] = callback

    async def stop_notify(self, uuid: str, **kwargs) -> None:
        self._notify_callbacks.pop(uuid.upper(), None)

    async def write_gatt_char(
        self, uuid: str, data: bytes | bytearray, response: bool = False, **kwargs
    ) -> None:
        from simulator.command_handler import handle
        from ble_client import CHAR_TX_UUID
        responses = handle(self._state, bytes(data))
        for resp in responses:
            await self._push(CHAR_TX_UUID, resp)

    async def push_event(self, data: bytes) -> None:
        """Inject a Device→PC event packet (called by simulator CLI)."""
        from ble_client import CHAR_TX_UUID
        await self._push(CHAR_TX_UUID, data)

    async def _push(self, uuid: str, data: bytes) -> None:
        cb = self._notify_callbacks.get(uuid.upper())
        if cb is None:
            return
        try:
            result = cb(None, bytearray(data))
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.warning("[SIM] Notify callback error: %s", exc)
