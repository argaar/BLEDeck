"""Record mouse clicks and keyboard presses into MacroStep lists."""
from __future__ import annotations
import logging
import threading
import time
from typing import Callable

from pynput.mouse import Button, Listener as MouseListener
from pynput.keyboard import Key, KeyCode, Listener as KeyboardListener

from macro_models import ClickStep, KeyStep, MacroStep, SleepStep
from win32_utils import get_window_at_point

logger = logging.getLogger(__name__)

# Auto-stop the recorder after this many seconds of no observed mouse/keyboard
# events. Limits accidental capture if the user forgets to press Stop.
_IDLE_AUTOSTOP_SECONDS = 60.0

_MODIFIER_KEYS = frozenset({
    Key.ctrl, Key.ctrl_l, Key.ctrl_r,
    Key.shift, Key.shift_l, Key.shift_r,
    Key.alt, Key.alt_l, Key.alt_r,
    Key.cmd, Key.cmd_l, Key.cmd_r,
})

_MODIFIER_NAMES: dict[Key, str] = {
    Key.ctrl: "ctrl", Key.ctrl_l: "ctrl", Key.ctrl_r: "ctrl",
    Key.shift: "shift", Key.shift_l: "shift", Key.shift_r: "shift",
    Key.alt: "alt", Key.alt_l: "alt", Key.alt_r: "alt",
    Key.cmd: "win", Key.cmd_l: "win", Key.cmd_r: "win",
}

_NAMED_KEYS: dict[Key, str] = {
    Key.enter: "enter", Key.space: "space", Key.tab: "tab",
    Key.backspace: "backspace", Key.delete: "delete", Key.esc: "esc",
    Key.up: "up", Key.down: "down", Key.left: "left", Key.right: "right",
    Key.home: "home", Key.end: "end",
    Key.page_up: "page_up", Key.page_down: "page_down",
    Key.f1: "f1", Key.f2: "f2", Key.f3: "f3", Key.f4: "f4",
    Key.f5: "f5", Key.f6: "f6", Key.f7: "f7", Key.f8: "f8",
    Key.f9: "f9", Key.f10: "f10", Key.f11: "f11", Key.f12: "f12",
}

_SLEEP_THRESHOLD_MS = 200  # gaps smaller than this are dropped


def _key_to_str(key: Key | KeyCode) -> str:
    if isinstance(key, KeyCode):
        if key.char:
            return key.char
        return f"vk{key.vk}"
    return _NAMED_KEYS.get(key, str(key).replace("Key.", ""))


class MacroRecorder:
    """Records click points and key presses. Esc stops recording."""

    def __init__(self, on_done: Callable[[list[MacroStep]], None]) -> None:
        self._on_done = on_done
        self._steps: list[MacroStep] = []
        self._last_event_time: float = 0.0
        self._active_modifiers: set[str] = set()
        self._mouse_listener: MouseListener | None = None
        self._keyboard_listener: KeyboardListener | None = None
        self._lock = threading.Lock()
        self._stopped = False
        self._idle_timer: threading.Timer | None = None

    def start(self) -> None:
        self._stopped = False
        self._steps = []
        self._last_event_time = time.monotonic()
        self._active_modifiers = set()

        self._mouse_listener = MouseListener(on_click=self._on_click)
        self._keyboard_listener = KeyboardListener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()
        self._reset_idle_timer()

    def stop(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            steps_snapshot = list(self._steps)
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._keyboard_listener:
            self._keyboard_listener.stop()
        self._on_done(steps_snapshot)

    # ------------------------------------------------------------------
    def _reset_idle_timer(self) -> None:
        """Restart the idle countdown. Called on every observed event so the
        timer only fires once activity has truly stopped for the configured
        window (default 60 s)."""
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        self._idle_timer = threading.Timer(_IDLE_AUTOSTOP_SECONDS, self._on_idle_timeout)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _on_idle_timeout(self) -> None:
        if self._stopped:
            return
        logger.info(
            "Macro recorder auto-stopped after %.0fs of idle time",
            _IDLE_AUTOSTOP_SECONDS,
        )
        self.stop()

    # ------------------------------------------------------------------
    def _record_sleep(self) -> None:
        now = time.monotonic()
        gap_ms = int((now - self._last_event_time) * 1000)
        if gap_ms > _SLEEP_THRESHOLD_MS:
            self._steps.append(SleepStep(duration_ms=gap_ms))
        self._last_event_time = now
        # Activity observed → reset the auto-stop window.
        self._reset_idle_timer()

    def _on_click(self, x: int, y: int, button: Button, pressed: bool) -> None:
        if not pressed or self._stopped:
            return
        with self._lock:
            self._record_sleep()
            btn_name = {Button.left: "left", Button.right: "right",
                        Button.middle: "middle"}.get(button, "left")
            # Identify the element under the cursor at click time
            anchor_str, rect = get_window_at_point(x, y)
            if rect is not None:
                self._steps.append(ClickStep(
                    x=x - rect[0], y=y - rect[1],
                    button=btn_name, relative_to=anchor_str,
                ))
            else:
                self._steps.append(ClickStep(x=x, y=y, button=btn_name, relative_to="abs"))

    def _on_key_press(self, key: Key | KeyCode | None) -> None:
        if self._stopped or key is None:
            return
        if key == Key.esc:
            self.stop()
            return
        with self._lock:
            if key in _MODIFIER_KEYS:
                mod_name = _MODIFIER_NAMES.get(key, "")  # type: ignore[arg-type]
                if mod_name:
                    self._active_modifiers.add(mod_name)
                return
            self._record_sleep()
            key_str = _key_to_str(key)
            modifiers = tuple(sorted(self._active_modifiers))
            self._steps.append(KeyStep(key=key_str, modifiers=modifiers))

    def _on_key_release(self, key: Key | KeyCode | None) -> None:
        if key is None:
            return
        with self._lock:
            if key in _MODIFIER_KEYS:
                mod_name = _MODIFIER_NAMES.get(key, "")  # type: ignore[arg-type]
                self._active_modifiers.discard(mod_name)
