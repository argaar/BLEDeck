import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_VALID_ACTION_TYPES = frozenset({"command", "macro"})
_VALID_STEP_TYPES = frozenset({"click", "key", "sleep"})
_MAX_PROFILES = 10
_SCHEMA_VERSION = 1

# Color format: "R,G,B,Brightness%" where each component is an integer.
# RGB are 0-255 and the brightness component is 0-100 (% scale). An empty
# string represents "no color set" and is accepted (used for unconfigured keys).
_COLOR_PATTERN = re.compile(
    r"^\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*$"
)


def _validate_color(value: str) -> None:
    """Raise ValueError when ``value`` is not a well-formed RGBW color string.

    Empty string is permitted (unconfigured key). Otherwise each of the four
    components must be a non-negative integer in the documented range.
    """
    if value == "":
        return
    match = _COLOR_PATTERN.match(value)
    if not match:
        raise ValueError(
            f"color {value!r} must be 'R,G,B,Brightness%' (e.g. '255,0,0,70')"
        )
    r, g, b, w = (int(c) for c in match.groups())
    for name, n, limit in (("R", r, 255), ("G", g, 255), ("B", b, 255), ("brightness", w, 100)):
        if not (0 <= n <= limit):
            raise ValueError(
                f"color {value!r}: {name} component {n} out of range 0..{limit}"
            )


def _validate_profiles(data: object) -> "List[ProfileData]":
    """Validate deserialized profiles JSON structure. Raises ValueError on invalid input."""
    if not isinstance(data, list):
        raise ValueError("profiles must be a JSON array")
    if len(data) > _MAX_PROFILES:
        raise ValueError(f"profile count {len(data)} exceeds limit {_MAX_PROFILES}")
    for pi, profile in enumerate(data):
        if not isinstance(profile, dict):
            raise ValueError(f"profile[{pi}] must be an object")
        if "name" in profile and not isinstance(profile["name"], str):
            raise ValueError(f"profile[{pi}].name must be a string")
        keys = profile.get("keys", {})
        if not isinstance(keys, dict):
            raise ValueError(f"profile[{pi}].keys must be an object")
        for ki, key_data in keys.items():
            if not isinstance(key_data, dict):
                raise ValueError(f"profile[{pi}].keys[{ki!r}] must be an object")
            color = key_data.get("color", "")
            if not isinstance(color, str):
                raise ValueError(
                    f"profile[{pi}].keys[{ki!r}].color must be a string"
                )
            try:
                _validate_color(color)
            except ValueError as e:
                raise ValueError(f"profile[{pi}].keys[{ki!r}].{e}") from e
            action_type = key_data.get("action_type", "command")
            if action_type not in _VALID_ACTION_TYPES:
                raise ValueError(
                    f"profile[{pi}].keys[{ki!r}].action_type {action_type!r} "
                    f"must be one of {sorted(_VALID_ACTION_TYPES)}"
                )
            if action_type == "macro":
                steps = key_data.get("macro", [])
                if not isinstance(steps, list):
                    raise ValueError(
                        f"profile[{pi}].keys[{ki!r}].macro must be an array"
                    )
                for si, step in enumerate(steps):
                    if not isinstance(step, dict):
                        raise ValueError(
                            f"profile[{pi}].keys[{ki!r}].macro[{si}] must be an object"
                        )
                    step_type = step.get("type")
                    if step_type not in _VALID_STEP_TYPES:
                        raise ValueError(
                            f"profile[{pi}].keys[{ki!r}].macro[{si}].type "
                            f"{step_type!r} must be one of {sorted(_VALID_STEP_TYPES)}"
                        )
    return data  # type: ignore[return-value]


def _config_dir() -> Path:
    base = os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Roaming")
    candidates = [
        Path(base) / "BLEDeck",
        Path.home() / ".bledeck",
        Path(tempfile.gettempdir()) / "bledeck",
    ]
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            return d
        except OSError as e:
            logger.warning("Could not create config dir %s: %s", d, e)
    # Last resort: return the temp candidate even if mkdir failed; caller
    # will surface I/O errors via save_profiles_to.
    return candidates[-1]


CONFIG_PATH = _config_dir() / "profiles.json"

ProfileData = Dict[str, Any]


def default_profiles() -> List[ProfileData]:
    return [
        {
            "name": "Default",
            "keys": {
                "0": {"label": "Notepad", "color": "100,150,255,70", "command": "notepad.exe", "_sample": True},
                "1": {"label": "Calculator", "color": "255,100,100,70", "command": "calc.exe", "_sample": True},
                "2": {"label": "Explorer", "color": "100,255,100,70", "command": "explorer.exe", "_sample": True},
                "3": {"label": "", "color": "", "command": ""},
                "4": {"label": "", "color": "", "command": ""},
                "5": {"label": "", "color": "", "command": ""},
                "6": {"label": "", "color": "", "command": ""},
                "7": {"label": "", "color": "", "command": ""},
                "8": {"label": "", "color": "", "command": ""},
                "9": {"label": "", "color": "", "command": ""},
                "10": {"label": "", "color": "", "command": ""},
                "11": {"label": "", "color": "", "command": ""},
                "12": {"label": "", "color": "", "command": ""},
                "13": {"label": "", "color": "", "command": ""},
                "14": {"label": "", "color": "", "command": ""},
                "15": {"label": "", "color": "", "command": ""},
            },
        }
    ]


def load_profiles_from(path: Path) -> List[ProfileData]:
    """Load profiles from an arbitrary path. Raises on I/O, JSON, or schema errors.

    Accepts both schema forms:
      - legacy: bare JSON array of profiles
      - v1:     {"version": 1, "profiles": [...]}
    """
    with open(path, "r", encoding="utf-8") as f:
        data: object = json.load(f)
    if isinstance(data, dict) and "profiles" in data:
        raw = data.get("profiles")
    else:
        raw = data
    profiles = _validate_profiles(raw)
    for profile in profiles:
        if "keys" not in profile:
            profile["keys"] = {}
        if "name" not in profile:
            profile["name"] = "Unnamed Profile"
    return profiles


def save_profiles_to(path: Path, profiles: List[ProfileData]) -> bool:
    """Save profiles to an arbitrary path. Returns False on OSError.

    Atomic write: serialise to a sibling .tmp file then os.replace into place.
    Always serialised under the v1 schema envelope.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {"version": _SCHEMA_VERSION, "profiles": profiles}
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError as e:
        logger.error("Error saving profiles to %s: %s", path, e)
        return False


def load_profiles() -> List[ProfileData]:
    if not CONFIG_PATH.exists():
        profiles = default_profiles()
        save_profiles(profiles)
        return profiles
    try:
        return load_profiles_from(CONFIG_PATH)
    except (json.JSONDecodeError, FileNotFoundError, ValueError, OSError) as e:
        logger.warning("Could not load profiles from %s: %s", CONFIG_PATH, e)
        try:
            backup = CONFIG_PATH.with_suffix(".corrupt.json")
            CONFIG_PATH.replace(backup)
            logger.warning("Renamed corrupt profile file to %s", backup)
        except OSError as rename_err:
            logger.warning("Could not back up corrupt profile file: %s", rename_err)
        return default_profiles()


def save_profiles(profiles: List[ProfileData]) -> bool:
    return save_profiles_to(CONFIG_PATH, profiles)


def create_new_profile(name: str = "New Profile") -> ProfileData:
    return {
        "name": name,
        "keys": {},
    }
