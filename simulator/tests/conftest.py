import sys
from pathlib import Path

# Make `simulator` and `ble_protocol` importable from the project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import simulator  # noqa: E402, F401  trigger windows_app sys.path shim

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def reset_context():
    """Reset module-global DeviceState + active client between tests."""
    from simulator._context import reset_state, set_active_client

    reset_state()
    set_active_client(None)
    yield
    reset_state()
    set_active_client(None)
