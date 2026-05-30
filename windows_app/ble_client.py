import os
import sys
from pathlib import Path

DEVICE_NAME  = "BLEDeck"
SERVICE_UUID = "4FAFC201-1FB5-459E-8FCC-C5C9C331914B"
CHAR_TX_UUID = "BEB5483E-36E1-4688-B7F5-EA07361B26A8"
CHAR_RX_UUID = "EAB5483E-36E1-4688-B7F5-EA07361B26A9"

if os.environ.get("BLEDECK_SIM") == "1":
    # simulator/ lives at project root, which may not be in sys.path when
    # main.py is run as `python windows_app/main.py` (script dir is windows_app/).
    _ROOT = Path(__file__).resolve().parent.parent
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from simulator.fake_bleak_client import FakeBleakClient as BleakClient
    from simulator.fake_bleak_client import FakeBleakScanner as BleakScanner
else:
    from bleak import BleakClient, BleakScanner  # type: ignore[assignment]

__all__ = [
    "BleakClient", "BleakScanner",
    "DEVICE_NAME", "SERVICE_UUID", "CHAR_TX_UUID", "CHAR_RX_UUID",
]
