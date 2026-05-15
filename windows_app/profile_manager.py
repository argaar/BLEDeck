import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

CONFIG_PATH = "profiles.json"

ProfileData = Dict[str, Any]


def load_profiles() -> List[ProfileData]:
    if not os.path.exists(CONFIG_PATH):
        default_profiles: List[ProfileData] = [
            {
                "name": "Default",
                "keys": {
                    "0": {"label": "Notepad", "color": "100,150,255,70", "command": "notepad.exe"},
                    "1": {"label": "Calculator", "color": "255,100,100,70", "command": "calc.exe"},
                    "2": {"label": "Explorer", "color": "100,255,100,70", "command": "explorer.exe"},
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
                    "15": {"label": "", "color": "", "command": ""}
                }
            }
        ]
        save_profiles(default_profiles)
        return default_profiles

    try:
        with open(CONFIG_PATH, "r") as f:
            profiles: List[ProfileData] = json.load(f)
            for profile in profiles:
                if 'keys' not in profile:
                    profile['keys'] = {}
                if 'name' not in profile:
                    profile['name'] = "Unnamed Profile"
            return profiles
    except (json.JSONDecodeError, FileNotFoundError):
        return [{"name": "Default", "keys": {}}]


def save_profiles(profiles: List[ProfileData]) -> bool:
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(profiles, f, indent=2)
        return True
    except Exception as e:
        logger.error("Error saving profiles: %s", e)
        return False


def create_new_profile(name: str = "New Profile") -> ProfileData:
    return {
        "name": name,
        "keys": {}
    }