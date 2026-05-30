"""Tests for app_settings module (v0.2.3)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app_settings


@pytest.fixture
def tmp_settings(tmp_path, monkeypatch):
    target = tmp_path / "app_settings.json"
    monkeypatch.setattr(app_settings, "SETTINGS_PATH", target)
    return target


def test_load_defaults_when_missing(tmp_settings):
    s = app_settings.load_settings()
    assert s["preferred_device_mac"] is None


def test_save_load_round_trip(tmp_settings):
    assert app_settings.save_settings({"preferred_device_mac": "AA:BB:CC:DD:EE:FF"}) is True
    assert app_settings.load_settings()["preferred_device_mac"] == "AA:BB:CC:DD:EE:FF"


def test_save_is_atomic_no_tmp_left(tmp_settings):
    assert app_settings.save_settings({"preferred_device_mac": "AA:BB"}) is True
    assert tmp_settings.exists()
    assert not tmp_settings.with_suffix(tmp_settings.suffix + ".tmp").exists()


def test_save_failure_preserves_original(tmp_settings, monkeypatch):
    tmp_settings.write_text(
        json.dumps({"preferred_device_mac": "00:00:00:00:00:00"}),
        encoding="utf-8",
    )
    original = tmp_settings.read_bytes()

    def boom(*_a, **_kw):
        raise OSError("simulated replace failure")
    monkeypatch.setattr(app_settings.os, "replace", boom)

    assert app_settings.save_settings({"preferred_device_mac": "FF:FF"}) is False
    assert tmp_settings.read_bytes() == original


def test_corrupt_file_falls_back_to_defaults(tmp_settings):
    tmp_settings.write_text("{ broken json", encoding="utf-8")
    assert app_settings.load_settings()["preferred_device_mac"] is None


def test_non_dict_root_falls_back_to_defaults(tmp_settings):
    tmp_settings.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    assert app_settings.load_settings()["preferred_device_mac"] is None


def test_unknown_keys_dropped_on_load(tmp_settings):
    tmp_settings.write_text(
        json.dumps({
            "preferred_device_mac": "AA:BB",
            "future_key": "should be ignored",
        }),
        encoding="utf-8",
    )
    s = app_settings.load_settings()
    assert "future_key" not in s
    assert s["preferred_device_mac"] == "AA:BB"
