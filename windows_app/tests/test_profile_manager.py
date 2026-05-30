"""Tests for profile_manager module"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import profile_manager


def test_create_new_profile_default_name():
    profile = profile_manager.create_new_profile()
    assert profile["name"] == "New Profile"
    assert profile["keys"] == {}


def test_create_new_profile_custom_name():
    profile = profile_manager.create_new_profile("Custom")
    assert profile["name"] == "Custom"
    assert profile["keys"] == {}


def test_save_and_load_profiles(tmp_path, monkeypatch):
    test_path = tmp_path / "profiles.json"
    monkeypatch.setattr(profile_manager, "CONFIG_PATH", test_path)

    profiles = [
        {"name": "Test", "keys": {"0": {"label": "A", "color": "", "command": "calc.exe"}}}
    ]
    result = profile_manager.save_profiles(profiles)
    assert result is True
    assert test_path.exists()

    loaded = profile_manager.load_profiles()
    assert len(loaded) == 1
    assert loaded[0]["name"] == "Test"
    assert loaded[0]["keys"]["0"]["command"] == "calc.exe"


def test_load_profiles_creates_default_when_missing(tmp_path, monkeypatch):
    test_path = tmp_path / "profiles.json"
    monkeypatch.setattr(profile_manager, "CONFIG_PATH", test_path)

    profiles = profile_manager.load_profiles()
    assert len(profiles) == 1
    assert profiles[0]["name"] == "Default"
    assert "0" in profiles[0]["keys"]


def test_load_profiles_handles_corrupted_file(tmp_path, monkeypatch):
    test_path = tmp_path / "profiles.json"
    monkeypatch.setattr(profile_manager, "CONFIG_PATH", test_path)
    test_path.write_text("not json", encoding="utf-8")

    profiles = profile_manager.load_profiles()
    assert len(profiles) == 1
    assert profiles[0]["name"] == "Default"


def test_load_profiles_fills_missing_fields(tmp_path, monkeypatch):
    test_path = tmp_path / "profiles.json"
    monkeypatch.setattr(profile_manager, "CONFIG_PATH", test_path)
    test_path.write_text(json.dumps([{"name": "Partial"}]), encoding="utf-8")

    profiles = profile_manager.load_profiles()
    assert profiles[0]["keys"] == {}


def test_save_profiles_returns_false_on_error(tmp_path, monkeypatch):
    # Create a regular file, then try to treat it as a directory.
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("blocker", encoding="utf-8")
    test_path = blocker / "profiles.json"
    monkeypatch.setattr(profile_manager, "CONFIG_PATH", test_path)

    result = profile_manager.save_profiles([{"name": "Fail"}])
    assert result is False


def test_load_profiles_preserves_existing_data(tmp_path, monkeypatch):
    test_path = tmp_path / "profiles.json"
    monkeypatch.setattr(profile_manager, "CONFIG_PATH", test_path)
    test_path.write_text(json.dumps([
        {"name": "Work", "keys": {"5": {"label": "Browser", "color": "0,0,255,50", "command": "chrome.exe"}}}
    ]), encoding="utf-8")

    profiles = profile_manager.load_profiles()
    assert len(profiles) == 1
    assert profiles[0]["name"] == "Work"
    assert profiles[0]["keys"]["5"]["command"] == "chrome.exe"


def test_create_new_profile_structure():
    profile = profile_manager.create_new_profile("Gaming")
    assert "name" in profile
    assert "keys" in profile
    assert isinstance(profile["keys"], dict)


def test_utf8_profile_name_roundtrip(tmp_path, monkeypatch):
    test_path = tmp_path / "profiles.json"
    monkeypatch.setattr(profile_manager, "CONFIG_PATH", test_path)

    profiles = [{"name": "Emojiプロ🎹", "keys": {}}]
    profile_manager.save_profiles(profiles)
    loaded = profile_manager.load_profiles()
    assert loaded[0]["name"] == "Emojiプロ🎹"


def test_utf8_key_label_roundtrip(tmp_path, monkeypatch):
    test_path = tmp_path / "profiles.json"
    monkeypatch.setattr(profile_manager, "CONFIG_PATH", test_path)

    profiles = [{"name": "P", "keys": {"0": {"label": "Ouvrir", "color": "", "command": "notepad.exe"}}}]
    profile_manager.save_profiles(profiles)
    loaded = profile_manager.load_profiles()
    assert loaded[0]["keys"]["0"]["label"] == "Ouvrir"


def test_load_profiles_fills_missing_name(tmp_path, monkeypatch):
    test_path = tmp_path / "profiles.json"
    monkeypatch.setattr(profile_manager, "CONFIG_PATH", test_path)
    test_path.write_text(json.dumps([{"keys": {}}]), encoding="utf-8")

    profiles = profile_manager.load_profiles()
    assert profiles[0]["name"] == "Unnamed Profile"


def test_save_profiles_written_as_utf8(tmp_path, monkeypatch):
    test_path = tmp_path / "profiles.json"
    monkeypatch.setattr(profile_manager, "CONFIG_PATH", test_path)

    profile_manager.save_profiles([{"name": "Ñoño", "keys": {}}])
    raw = test_path.read_bytes()
    assert "Ñoño".encode("utf-8") in raw


def test_load_profiles_from_arbitrary_path(tmp_path):
    custom = tmp_path / "elsewhere" / "my_profiles.json"
    custom.parent.mkdir(parents=True)
    custom.write_text(json.dumps([{"name": "Custom", "keys": {"0": {"label": "X"}}}]),
                      encoding="utf-8")

    profiles = profile_manager.load_profiles_from(custom)
    assert profiles[0]["name"] == "Custom"
    assert profiles[0]["keys"]["0"]["label"] == "X"


def test_load_profiles_from_fills_missing_fields(tmp_path):
    custom = tmp_path / "p.json"
    custom.write_text(json.dumps([{}]), encoding="utf-8")

    profiles = profile_manager.load_profiles_from(custom)
    assert profiles[0]["name"] == "Unnamed Profile"
    assert profiles[0]["keys"] == {}


def test_load_profiles_from_raises_on_bad_json(tmp_path):
    custom = tmp_path / "p.json"
    custom.write_text("not json", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError):
        profile_manager.load_profiles_from(custom)


def test_save_profiles_to_arbitrary_path_creates_dirs(tmp_path):
    target = tmp_path / "new" / "sub" / "out.json"
    ok = profile_manager.save_profiles_to(target, [{"name": "X", "keys": {}}])
    assert ok is True
    assert target.exists()
    loaded = profile_manager.load_profiles_from(target)
    assert loaded[0]["name"] == "X"


def test_save_profiles_to_returns_false_on_error(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    target = blocker / "out.json"
    assert profile_manager.save_profiles_to(target, [{"name": "X"}]) is False


def test_load_multiple_profiles(tmp_path, monkeypatch):
    test_path = tmp_path / "profiles.json"
    monkeypatch.setattr(profile_manager, "CONFIG_PATH", test_path)

    profiles = [
        {"name": "A", "keys": {}},
        {"name": "B", "keys": {}},
        {"name": "C", "keys": {}},
    ]
    profile_manager.save_profiles(profiles)
    loaded = profile_manager.load_profiles()
    assert len(loaded) == 3
    assert [p["name"] for p in loaded] == ["A", "B", "C"]