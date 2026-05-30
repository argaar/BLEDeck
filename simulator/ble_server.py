"""
BLE GATT server via direct WinRT bindings — Mode B (real BLE advertising).
Windows-only. No external BLE library required; uses the winrt-* packages
that are already installed as bleak dependencies.

Device name cannot be set in WinRT advertisement — the Windows app connects
via service UUID filter (already implemented in main.py scan logic).
"""
import asyncio
import logging
import uuid as _uuid
from typing import Any

import simulator  # noqa: F401  trigger sys.path shim

from ble_client import DEVICE_NAME, SERVICE_UUID, CHAR_TX_UUID, CHAR_RX_UUID
from simulator.device_state import DeviceState
from simulator.command_handler import handle as cmd_handle

logger = logging.getLogger(__name__)

try:
    from winrt.windows.devices.bluetooth.genericattributeprofile import (
        GattServiceProvider,
        GattLocalCharacteristicParameters,
        GattCharacteristicProperties,
        GattProtectionLevel,
        GattServiceProviderAdvertisingParameters,
    )
    from winrt.windows.storage.streams import DataWriter
    _WINRT_AVAILABLE = True
except ImportError:
    _WINRT_AVAILABLE = False


class BLEServer:
    def __init__(self, state: DeviceState, loop: asyncio.AbstractEventLoop) -> None:
        if not _WINRT_AVAILABLE:
            raise RuntimeError(
                "WinRT BLE packages not found.\n"
                "These are installed with bleak — ensure bleak is installed:\n"
                "  pip install bleak\n"
                "Or use loopback mode: python -m simulator"
            )
        self._state = state
        self._loop = loop
        self._service_provider: Any = None
        self._tx_char: Any = None
        self._rx_char: Any = None

    async def start(self) -> None:
        result = await GattServiceProvider.create_async(_uuid.UUID(SERVICE_UUID))
        if result.service_provider is None:
            raise RuntimeError(
                f"GattServiceProvider creation failed (error={result.error}).\n"
                "Possible causes:\n"
                "  • No Bluetooth adapter present\n"
                "  • BLE peripheral/server role not supported by adapter\n"
                "  • Bluetooth service not running (Windows: check Services)\n"
                "Fallback: python -m simulator"
            )
        self._service_provider = result.service_provider

        # TX characteristic: notify (device → app)
        tx_params = GattLocalCharacteristicParameters()
        tx_params.characteristic_properties = GattCharacteristicProperties.NOTIFY
        tx_params.read_protection_level = GattProtectionLevel.PLAIN
        tx_params.write_protection_level = GattProtectionLevel.PLAIN
        tx_result = await self._service_provider.service.create_characteristic_async(
            _uuid.UUID(CHAR_TX_UUID), tx_params
        )
        self._tx_char = tx_result.characteristic

        # RX characteristic: write (app → device)
        rx_params = GattLocalCharacteristicParameters()
        rx_params.characteristic_properties = (
            GattCharacteristicProperties.WRITE
            | GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE
        )
        rx_params.read_protection_level = GattProtectionLevel.PLAIN
        rx_params.write_protection_level = GattProtectionLevel.PLAIN
        rx_result = await self._service_provider.service.create_characteristic_async(
            _uuid.UUID(CHAR_RX_UUID), rx_params
        )
        self._rx_char = rx_result.characteristic
        self._rx_char.add_write_requested(self._on_write)

        adv_params = GattServiceProviderAdvertisingParameters()
        adv_params.is_connectable = True
        adv_params.is_discoverable = True
        self._service_provider.start_advertising_with_parameters(adv_params)

        logger.info("[BLE] Advertising (service UUID: %s)", SERVICE_UUID)
        logger.info(
            "[BLE] Note: '%s' device name may not appear in Windows scans — "
            "app connects via service UUID filter automatically.",
            DEVICE_NAME,
        )

    async def stop(self) -> None:
        if self._service_provider:
            self._service_provider.stop_advertising()
            self._service_provider = None
            logger.info("[BLE] Stopped")

    async def send_event(self, data: bytes) -> None:
        """Push Device→PC notification to all subscribed clients."""
        if self._tx_char is None:
            return
        writer = DataWriter()
        writer.write_bytes(bytearray(data))
        buf = writer.detach_buffer()
        await self._tx_char.notify_value_async(buf)

    def _on_write(self, sender: Any, args: Any) -> None:
        """WinRT write callback — runs in a WinRT thread, not on the asyncio loop."""
        deferral = args.get_deferral()
        asyncio.run_coroutine_threadsafe(
            self._handle_write(args, deferral), self._loop
        )

    async def _handle_write(self, args: Any, deferral: Any) -> None:
        raw: bytes = b""
        try:
            request = await args.get_request_async()
            raw = bytes(request.value)
            request.respond()
            try:
                for resp in cmd_handle(self._state, raw):
                    await self.send_event(resp)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "[BLE] cmd dispatch failed: %s (raw=%r)", exc, raw
                )
        finally:
            deferral.complete()
