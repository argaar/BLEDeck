"""Dispatch key actions: launch executables or macro playback."""
from __future__ import annotations
import logging
import shlex
import shutil
import subprocess
import sys
import atexit
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from macro_models import MacroStep, macro_from_list
import macro_player

logger = logging.getLogger(__name__)

LogFn = Callable[[str], None]
_ActiveKey = tuple[int, int]  # (profile_index, key_id)


# Reasonable upper bound for a human-driven keypad. Macros + shell commands
# launched from device keys reuse this pool instead of spawning a fresh
# OS thread per press (saves ~0.5–2 ms per launch on Windows). One pool
# instance is shared across every ActionRunner; idle threads sit cheap.
_ACTION_THREAD_POOL = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="bledeck-action",
)

# Don't block interpreter shutdown on lingering macro / Popen workers.
# A stuck macro should not prevent the GUI process from exiting cleanly.
atexit.register(_ACTION_THREAD_POOL.shutdown, wait=False, cancel_futures=True)


class ActionRunner:
    """Runs commands or macros for BLEDeck key presses with re-entrancy guard."""

    def __init__(self) -> None:
        self._active: set[_ActiveKey] = set()
        self._lock = threading.Lock()

    def run(self, key_data: dict[str, Any], key_id: int, profile_index: int,
            log_fn: LogFn) -> None:
        """
        Dispatch action for a key press.
        Drops re-entrant calls for the same (profile, key) pair.
        """
        guard = (profile_index, key_id)
        with self._lock:
            if guard in self._active:
                log_fn(f"⚠️ Key {key_id} still running, skipping")
                return
            self._active.add(guard)

        action_type = key_data.get("action_type", "command")
        thread_started = False
        try:
            if action_type == "macro":
                raw_steps = key_data.get("macro", [])
                if not raw_steps:
                    log_fn(f"⚠️ No macro steps for key {key_id}")
                    return
                try:
                    steps = macro_from_list(raw_steps)
                except (ValueError, KeyError) as e:
                    log_fn(f"❌ Invalid macro step: {e}")
                    return
                # Guard released inside worker when macro finishes
                try:
                    _ACTION_THREAD_POOL.submit(
                        self._run_macro, steps, guard, log_fn,
                    )
                    thread_started = True
                except Exception as e:
                    log_fn(f"❌ Failed to start macro thread: {e}")
                    return
                return
            else:
                command = key_data.get("command", "")
                if not command:
                    log_fn(f"⚠️ No command for key {key_id}")
                    return
                # Launch command in a worker thread so a slow Popen (e.g. a
                # cold-cache exe) cannot freeze the GUI thread.
                try:
                    _ACTION_THREAD_POOL.submit(
                        self._run_command_threaded, command, guard, log_fn,
                    )
                    thread_started = True
                except Exception as e:
                    log_fn(f"❌ Failed to start command thread: {e}")
                    return
                return
        finally:
            if not thread_started:
                with self._lock:
                    self._active.discard(guard)

    def _run_command_threaded(self, command: str, guard: _ActiveKey,
                              log_fn: LogFn) -> None:
        try:
            self._run_command(command, log_fn)
        finally:
            with self._lock:
                self._active.discard(guard)

    def _run_macro(self, steps: list[MacroStep], guard: _ActiveKey,
                   log_fn: LogFn) -> None:
        try:
            log_fn(f"▶ Running macro ({len(steps)} steps)...")
            macro_player.play(steps)
            log_fn("✅ Macro complete")
        except Exception as e:
            logger.exception("Macro playback error")
            log_fn(f"❌ Macro error: {e}")
        finally:
            with self._lock:
                self._active.discard(guard)

    def _run_command(self, command: str, log_fn: LogFn) -> None:
        # No shell expansion: prevents chained injection from a tampered
        # profiles.json (e.g. `calc & del *.*`). User must invoke shells
        # explicitly, e.g. `cmd /c "echo Hello"`.
        try:
            argv = shlex.split(command, posix=False)
        except ValueError as e:
            log_fn(f"❌ Invalid command syntax: {e}")
            return
        if not argv:
            log_fn("⚠️ Empty command")
            return

        exe_token = argv[0].strip('"')
        resolved = shutil.which(exe_token) or exe_token
        if not Path(resolved).is_file():
            log_fn(f"❌ Executable not found: {exe_token}")
            return

        try:
            # CREATE_NO_WINDOW suppresses a console flash for CLI tools without
            # hiding GUI apps (notepad, calc, etc.). wShowWindow=SW_HIDE would
            # have made GUI apps launch invisible — avoid STARTF_USESHOWWINDOW.
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            subprocess.Popen(
                [resolved, *argv[1:]],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            log_fn(f"⚡ Executed: {command}")
        except Exception as e:
            log_fn(f"❌ Command failed: {e}")
