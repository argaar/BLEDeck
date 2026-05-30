"""REPL for controlling the simulator (used by both Mode A and Mode B)."""
import asyncio
import logging
from typing import Callable, Awaitable

import simulator  # noqa: F401  trigger sys.path shim
from simulator.device_state import DeviceState
from simulator import event_emitter as emit

logger = logging.getLogger(__name__)

_HELP = """\
BLEDeck Simulator — commands:
  battery <n>          BATTERY_STATUS (0-100, or -1 = no battery/USB)
  press <idx> <char>   KEY_PRESSED    (profile idx 0-based, single char)
  button <name>        BUTTON_PRESSED (current profile, button name)
  profile <idx>        PROFILE_CHANGED + update local state (0-based)
  state                Print current device state
  help / ?             Show this help
  quit / q             Exit
"""


async def run_cli(
    state: DeviceState,
    send_fn: Callable[[bytes], Awaitable[None]],
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Async REPL — reads stdin in an executor so the event loop stays live."""
    print(_HELP)
    while True:
        try:
            line: str = await loop.run_in_executor(
                None, lambda: input("sim> ").strip()
            )
        except (EOFError, KeyboardInterrupt):
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        try:
            if cmd in ("quit", "q", "exit"):
                break
            elif cmd in ("help", "?"):
                print(_HELP)
            elif cmd == "state":
                _print_state(state)
            elif cmd == "battery":
                pct = int(parts[1]) if len(parts) > 1 else state.battery_percent
                pct = max(-1, min(100, pct))
                state.battery_percent = pct
                await send_fn(emit.battery_status(pct))
                print(f"  → BATTERY_STATUS {pct}")
            elif cmd == "press":
                idx = int(parts[1]) if len(parts) > 1 else state.current_profile_index
                char = parts[2] if len(parts) > 2 else "A"
                if len(char) != 1:
                    print(f"  Error: 'press' requires a single character, got {char!r}")
                    continue
                await send_fn(emit.key_pressed(idx, char))
                print(f"  → KEY_PRESSED profile={idx} key='{char}'")
            elif cmd == "button":
                name = parts[1] if len(parts) > 1 else "key1"
                await send_fn(emit.button_pressed(state.current_profile_index, name))
                print(f"  → BUTTON_PRESSED profile={state.current_profile_index} name='{name}'")
            elif cmd == "profile":
                idx = int(parts[1]) if len(parts) > 1 else 0
                if not (0 <= idx <= 255):
                    print(f"  Error: profile index must be in 0..255, got {idx}")
                    continue
                state.current_profile_index = idx
                await send_fn(emit.profile_changed(idx))
                print(f"  → PROFILE_CHANGED {idx}")
            else:
                print(f"  Unknown: '{cmd}'. Type 'help'.")
        except (IndexError, ValueError) as exc:
            print(f"  Error: {exc}")


def _print_state(state: DeviceState) -> None:
    print(f"  profile_index : {state.current_profile_index}")
    print(f"  profiles      : {dict(state.profiles)}")
    print(f"  locked        : {state.locked}")
    print(f"  battery       : {state.battery_percent}%")
    lit = [(i, c) for i, c in enumerate(state.rgb_matrix) if any(c)]
    print(f"  rgb_matrix    : {len(lit)}/16 keys lit")
