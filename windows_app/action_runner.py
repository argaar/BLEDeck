"""Dispatch key actions: shell commands or macro playback."""
from __future__ import annotations
import logging
import subprocess
import sys
import threading
from typing import Any, Callable

from macro_models import MacroStep, macro_from_list
import macro_player

logger = logging.getLogger(__name__)

LogFn = Callable[[str], None]
_ActiveKey = tuple[int, int]  # (profile_index, key_id)


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
        try:
            if action_type == "macro":
                raw_steps = key_data.get("macro", [])
                if not raw_steps:
                    log_fn(f"⚠️ No macro steps for key {key_id}")
                    return
                steps = macro_from_list(raw_steps)
                # Guard released inside thread when macro finishes
                thread = threading.Thread(
                    target=self._run_macro,
                    args=(steps, guard, log_fn),
                    daemon=True,
                )
                try:
                    thread.start()
                except Exception as e:
                    with self._lock:
                        self._active.discard(guard)
                    log_fn(f"❌ Failed to start macro thread: {e}")
                    return
                return
            else:
                command = key_data.get("command", "")
                if not command:
                    log_fn(f"⚠️ No command for key {key_id}")
                    return
                self._run_command(command, log_fn)
        finally:
            if action_type != "macro":
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
        try:
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
            )
            log_fn(f"⚡ Executed: {command}")
        except Exception as e:
            log_fn(f"❌ Command failed: {e}")
