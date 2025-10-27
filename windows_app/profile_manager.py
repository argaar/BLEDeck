import json
import os

CONFIG_PATH = "profiles.json"

def load_profiles():
    if not os.path.exists(CONFIG_PATH):
        # Create default profiles with some example actions
        default_profiles = [
            {
                "name": "Default",
                "actions": {
                    "0": "notepad.exe",
                    "1": "calc.exe",
                    "2": "explorer.exe"
                }
            },
            {
                "name": "Development",
                "actions": {
                    "0": "code .",
                    "1": "cmd",
                    "2": "git status"
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
                if 'actions' not in profile:
                    profile['actions'] = {}
                if 'name' not in profile:
                    profile['name'] = "Unnamed Profile"
            return profiles
    except (json.JSONDecodeError, FileNotFoundError):
        # Return default if file is corrupted
        return [{"name": "Default", "actions": {}}]

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
        "actions": {}
    }

def duplicate_profile(profile, new_name=None):
    """Duplicate an existing profile"""
    new_profile = profile.copy()
    new_profile['actions'] = profile['actions'].copy()
    if new_name:
        new_profile['name'] = new_name
    else:
        new_profile['name'] = f"{profile['name']} (Copy)"
    return new_profile
