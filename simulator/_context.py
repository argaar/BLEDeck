"""Module-level singletons for loopback mode (Mode A)."""
from simulator.device_state import DeviceState

_state: DeviceState = DeviceState()
_active_client: object | None = None


def get_state() -> DeviceState:
    return _state


def reset_state() -> DeviceState:
    """Replace the module-global DeviceState with a fresh instance.

    Used by tests to guarantee isolation between cases that mutate state.
    Returns the new state for convenience.
    """
    global _state
    _state = DeviceState()
    return _state


def get_active_client() -> object | None:
    return _active_client


def set_active_client(client: object | None) -> None:
    global _active_client
    _active_client = client
