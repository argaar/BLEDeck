"""Persistent app-level settings (separate from profiles).

Stored at ``%APPDATA%\\BLEDeck\\app_settings.json`` next to ``profiles.json``.
Holds preferences that survive across sessions but do not belong in a
profile file (e.g. preferred BLE device MAC, future window-geometry hints).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from profile_manager import CONFIG_PATH

logger = logging.getLogger(__name__)

SETTINGS_PATH = CONFIG_PATH.parent / "app_settings.json"

_DEFAULT: Dict[str, Any] = {
    "preferred_device_mac": None,
}


def load_settings() -> Dict[str, Any]:
    """Return a settings dict, merging persisted values onto the defaults.

    Missing/corrupt files yield a fresh defaults dict so callers can rely on
    the keys always being present.
    """
    if not SETTINGS_PATH.exists():
        return dict(_DEFAULT)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("settings root must be an object")
    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning("Could not load %s (%s); using defaults", SETTINGS_PATH, e)
        return dict(_DEFAULT)
    merged = dict(_DEFAULT)
    merged.update({k: v for k, v in data.items() if k in _DEFAULT})
    return merged


def save_settings(settings: Dict[str, Any]) -> bool:
    """Atomically persist settings. Returns False on OSError."""
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_PATH.with_suffix(SETTINGS_PATH.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        os.replace(tmp, SETTINGS_PATH)
        return True
    except OSError as e:
        logger.error("Error saving %s: %s", SETTINGS_PATH, e)
        return False
