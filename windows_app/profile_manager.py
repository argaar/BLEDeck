import json
import os

CONFIG_PATH = "profiles.json"

def load_profiles():
    if not os.path.exists(CONFIG_PATH):
        # Create default profiles with some example keys
        default_profiles = [
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
            profiles = json.load(f)
            # Ensure each profile has required fields
            for profile in profiles:
                if 'keys' not in profile:
                    profile['keys'] = {}
                if 'name' not in profile:
                    profile['name'] = "Unnamed Profile"
            return profiles
    except (json.JSONDecodeError, FileNotFoundError):
        # Return default if file is corrupted
        return [{"name": "Default", "keys": {}}]

def save_profiles(profiles):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(profiles, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving profiles: {e}")
        return False

def create_new_profile(name="New Profile"):
    """Create a new empty profile"""
    return {
        "name": name,
        "keys": {}
    }

def duplicate_profile(profile, new_name=None):
    """Duplicate an existing profile"""
    new_profile = profile.copy()
    new_profile['keys'] = profile['keys'].copy()
    if new_name:
        new_profile['name'] = new_name
    else:
        new_profile['name'] = f"{profile['name']} (Copy)"
    return new_profile
