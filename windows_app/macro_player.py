"""Synchronous macro playback. Call play() from a worker thread."""
from __future__ import annotations
import logging
import time
from typing import Any

from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Key, Controller as KeyboardController

from macro_models import ClickStep, KeyStep, MacroStep, SleepStep
from win32_utils import find_window_by_title, get_foreground_window_rect, get_monitor_rect

logger = logging.getLogger(__name__)

_BUTTON_MAP: dict[str, Button] = {
    "left": Button.left,
    "right": Button.right,
    "middle": Button.middle,
}

_MODIFIER_MAP: dict[str, Any] = {
    "ctrl": Key.ctrl,
    "shift": Key.shift,
    "alt": Key.alt,
    "win": Key.cmd,
}


def _resolve_anchor(relative_to: str) -> tuple[int, int] | None:
    """
    Return (dx, dy) origin for relative_to string, or None if absolute.

    "window:<title>"  → top-left of the first matching visible window
    "monitor:<N>"     → top-left of monitor N (0 = leftmost)
    "" / "abs"        → None (use coordinates as-is)
    """
    if not relative_to or relative_to == "abs":
        return None

    if relative_to.startswith("window:"):
        title = relative_to[7:]
        rect = find_window_by_title(title) if title else get_foreground_window_rect()
        if rect:
            return rect[0], rect[1]
        logger.warning("Window %r not found for playback; using absolute coords", title)
        return None

    if relative_to.startswith("monitor:"):
        try:
            idx = int(relative_to[8:])
        except ValueError:
            return None
        rect = get_monitor_rect(idx)
        if rect:
            return rect[0], rect[1]
        logger.warning("Monitor %s not found; using absolute coords", relative_to[8:])
        return None

    return None


def _resolve_key(key_str: str) -> Any:
    """Resolve a key string to a pynput Key or a char."""
    try:
        return Key[key_str.lower()]
    except KeyError:
        pass
    if len(key_str) == 1:
        return key_str
    logger.warning("Unknown key %r, treating as char", key_str)
    return key_str


def play(steps: list[MacroStep]) -> None:
    """Execute macro steps synchronously. Call from a worker thread."""
    mouse = MouseController()
    keyboard = KeyboardController()

    for step in steps:
        if isinstance(step, ClickStep):
            x, y = step.x, step.y
            origin = _resolve_anchor(step.relative_to)
            if origin:
                x += origin[0]
                y += origin[1]
            mouse.position = (x, y)
            time.sleep(0.05)
            btn = _BUTTON_MAP.get(step.button, Button.left)
            mouse.click(btn)

        elif isinstance(step, KeyStep):
            modifiers = [_MODIFIER_MAP[m] for m in step.modifiers if m in _MODIFIER_MAP]
            key = _resolve_key(step.key)
            for mod in modifiers:
                keyboard.press(mod)
            keyboard.press(key)
            keyboard.release(key)
            for mod in reversed(modifiers):
                keyboard.release(mod)

        elif isinstance(step, SleepStep):
            time.sleep(step.duration_ms / 1000.0)
