"""
BLEDeck Device Simulator
========================

Mode A — loopback (default):
    python -m simulator              (from project root)
    python __main__.py               (from inside simulator/)
    BLEDECK_SIM=1 python windows_app/main.py   (app-side; CLI starts automatically)

    No Bluetooth radio needed. The app uses FakeBleakClient instead of
    bleak.BleakClient when BLEDECK_SIM=1 is set.

Mode B — real BLE (--ble):
    python -m simulator --ble

    Advertises via WinRT GattServiceProvider with the correct service/characteristic
    UUIDs. The Windows app connects normally via Bluetooth.
    Requires the winrt-* packages installed with bleak.
    Note: same-machine BLE self-connection is not supported on Windows — run
    the simulator and the app on different machines.
"""
import sys
import asyncio
import argparse
import logging
from pathlib import Path

# Allow running as `python __main__.py` from inside simulator/ as well as
# `python -m simulator` from the project root.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import simulator  # noqa: F401  trigger windows_app sys.path shim

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BLEDeck Device Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--ble",
        action="store_true",
        help="Mode B: real BLE via WinRT GattServiceProvider (requires bleak + BT adapter)",
    )
    args = parser.parse_args()

    if args.ble:
        _run_real_ble()
    else:
        _run_loopback()


def _run_real_ble() -> None:
    from simulator.ble_server import _WINRT_AVAILABLE

    # Windows blocks BLE self-connection: a single machine cannot host the
    # GATT server AND act as the BLE central. Print this upfront so the
    # operator does not waste time waiting for a same-machine app to connect.
    if sys.platform == "win32":
        logger.warning(
            "Mode B requires two machines on Windows. The BLE stack does not "
            "allow self-connection — run the Windows app on a SECOND PC."
        )

    if not _WINRT_AVAILABLE:
        logger.warning("WinRT BLE packages not found — falling back to loopback mode.")
        logger.warning("Install bleak to get the required winrt-* packages: pip install bleak")
        _run_loopback()
        return

    from simulator.device_state import DeviceState
    from simulator.ble_server import BLEServer
    from simulator.cli import run_cli

    state = DeviceState()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = BLEServer(state=state, loop=loop)

    async def _main() -> None:
        try:
            await server.start()
        except RuntimeError as exc:
            # Top-level banner kept as print so the user always sees the
            # reason for the fallback, even if logging is reconfigured.
            print(f"\nERROR: {exc}\n")
            logger.warning("Falling back to loopback mode...")
            await _loopback_async(state, loop)
            return
        try:
            await run_cli(state, server.send_event, loop)
        finally:
            await server.stop()

    try:
        loop.run_until_complete(_main())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


def _run_loopback() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    from simulator._context import get_state
    state = get_state()
    try:
        loop.run_until_complete(_loopback_async(state, loop))
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


async def _loopback_async(state, loop) -> None:
    from simulator._context import get_active_client
    from simulator.cli import run_cli

    async def _send(data: bytes) -> None:
        client = get_active_client()
        if client is None:
            print("  [SIM] No app connected yet. Start app with BLEDECK_SIM=1.")
            return
        await client.push_event(data)  # type: ignore[attr-defined]

    print("[SIM] Loopback mode. Start the app with BLEDECK_SIM=1.")
    await run_cli(state, _send, loop)


if __name__ == "__main__":
    main()
