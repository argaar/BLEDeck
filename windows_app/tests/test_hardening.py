"""Tests for v0.2.2 hardening: resource path resolution, atomic save,
profiles.json schema v1 round-trip, and BUTTON_PRESSED parser contract.

These tests pin behaviour added in the v0.2.2 hardening sweep so future
refactors cannot silently regress it. GUI-level bound checks in
``main.py:handle_notification`` are intentionally not exercised here —
they require a full QApplication and are covered by manual smoke testing.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

# Make the windows_app package importable without installing.
sys.path.insert(0, str(Path(__file__).parent.parent))

import ble_protocol
import profile_manager


# ---------------------------------------------------------------------------
# _resource_path — frozen (_MEIPASS) vs source resolution
# ---------------------------------------------------------------------------
class TestResourcePath:
    """``_resource_path`` lives in ``main.py`` but importing main pulls in
    PyQt5. Reimplement and assert the contract directly — the source-of-truth
    is the two-line resolver; the test verifies both branches behave."""

    @staticmethod
    def _resource_path(name: str, meipass: str | None) -> Path:
        # Mirrors windows_app/main.py:_resource_path. Kept in sync via this
        # test fixture; if main.py drifts, replicate the change here.
        base = Path(meipass) if meipass is not None else Path(__file__).resolve().parent.parent
        return base / name

    def test_source_mode_resolves_relative_to_module(self):
        # No _MEIPASS → resolves under windows_app/.
        path = self._resource_path("manual.md", meipass=None)
        assert path.name == "manual.md"
        assert path.parent.name == "windows_app"

    def test_frozen_mode_uses_meipass(self, tmp_path):
        # _MEIPASS set (PyInstaller) → resolves under the bundle dir.
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        path = self._resource_path("icon.ico", meipass=str(bundle))
        assert path == bundle / "icon.ico"

    def test_main_module_resolver_matches_contract(self, monkeypatch, tmp_path):
        """Smoke test against the real resolver in main.py, importing it
        lazily so the rest of the suite doesn't need PyQt5 in scope."""
        try:
            import main as app_main  # noqa: F401
        except ImportError:
            pytest.skip("main.py not importable (PyQt5 missing); resolver covered by helper above")

        # Source mode: _MEIPASS absent.
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        source_path = app_main._resource_path("manual.md")
        assert source_path.name == "manual.md"

        # Frozen mode: _MEIPASS set.
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        frozen_path = app_main._resource_path("manual.md")
        assert frozen_path == tmp_path / "manual.md"


# ---------------------------------------------------------------------------
# Atomic save — tmp file behaviour
# ---------------------------------------------------------------------------
class TestAtomicSave:
    def test_successful_save_leaves_no_tmp(self, tmp_path):
        target = tmp_path / "profiles.json"
        profiles = profile_manager.default_profiles()

        assert profile_manager.save_profiles_to(target, profiles) is True
        assert target.exists()
        # tmp file must not linger after a successful replace.
        assert not (tmp_path / "profiles.json.tmp").exists()

    def test_save_overwrites_existing_atomically(self, tmp_path):
        target = tmp_path / "profiles.json"
        # Seed with content the save must replace.
        target.write_text(json.dumps([{"name": "Stale", "keys": {}}]), encoding="utf-8")
        new_profiles = [{"name": "Fresh", "keys": {}}]

        ok = profile_manager.save_profiles_to(target, new_profiles)
        assert ok is True
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
        # Save always writes the v1 envelope.
        assert data["version"] == 1
        assert data["profiles"][0]["name"] == "Fresh"

    def test_save_failure_returns_false_without_corrupting_original(
        self, tmp_path, monkeypatch
    ):
        target = tmp_path / "profiles.json"
        target.write_text(
            json.dumps({"version": 1, "profiles": [{"name": "Stable", "keys": {}}]}),
            encoding="utf-8",
        )
        original_bytes = target.read_bytes()

        # Force os.replace to fail mid-save so we exercise the failure path.
        def boom(*_args, **_kwargs):
            raise OSError("simulated rename failure")

        monkeypatch.setattr(profile_manager.os, "replace", boom)

        result = profile_manager.save_profiles_to(target, [{"name": "Lost", "keys": {}}])
        assert result is False
        # Original file is untouched.
        assert target.read_bytes() == original_bytes


# ---------------------------------------------------------------------------
# Schema v1 round-trip
# ---------------------------------------------------------------------------
class TestSchemaV1Roundtrip:
    def test_legacy_bare_list_loads_then_saves_as_v1(self, tmp_path):
        target = tmp_path / "legacy.json"
        legacy_payload = [
            {"name": "Legacy", "keys": {"0": {"label": "X", "command": "x.exe"}}}
        ]
        target.write_text(json.dumps(legacy_payload), encoding="utf-8")

        loaded = profile_manager.load_profiles_from(target)
        assert loaded[0]["name"] == "Legacy"

        # Persist and confirm new file is v1 envelope.
        profile_manager.save_profiles_to(target, loaded)
        with open(target, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk["version"] == 1
        assert isinstance(on_disk["profiles"], list)
        assert on_disk["profiles"][0]["name"] == "Legacy"

    def test_v1_envelope_loads_back_identically(self, tmp_path):
        target = tmp_path / "v1.json"
        original = [
            {"name": "Alpha", "keys": {"0": {"label": "a", "command": "a.exe"}}},
            {"name": "Beta", "keys": {}},
        ]

        ok = profile_manager.save_profiles_to(target, original)
        assert ok is True

        reloaded = profile_manager.load_profiles_from(target)
        assert [p["name"] for p in reloaded] == ["Alpha", "Beta"]
        assert reloaded[0]["keys"]["0"]["command"] == "a.exe"

    def test_v1_envelope_explicit_dict_form(self, tmp_path):
        target = tmp_path / "explicit_v1.json"
        target.write_text(
            json.dumps(
                {
                    "version": 1,
                    "profiles": [{"name": "Dict", "keys": {}}],
                }
            ),
            encoding="utf-8",
        )

        loaded = profile_manager.load_profiles_from(target)
        assert len(loaded) == 1
        assert loaded[0]["name"] == "Dict"


# ---------------------------------------------------------------------------
# BUTTON_PRESSED — parser contract
# ---------------------------------------------------------------------------
class TestButtonPressedBounds:
    """The parser does not bound-check ``profile_index`` — that responsibility
    sits at the dispatch boundary in ``main.py:handle_notification``. These
    tests pin the parser contract so the bound check stays the only gate."""

    def test_parser_returns_arbitrary_profile_index_unchanged(self):
        payload = bytes([99, 3]) + b"CON"
        profile_idx, name = ble_protocol.parse_button_pressed(payload)
        assert profile_idx == 99
        assert name == "CON"

    def test_parser_returns_zero_profile_index(self):
        payload = bytes([0, 4]) + b"BACK"
        profile_idx, name = ble_protocol.parse_button_pressed(payload)
        assert profile_idx == 0
        assert name == "BACK"

    def test_parser_rejects_truncated_name(self):
        # name_len says 5 but only 2 bytes follow → ValueError.
        with pytest.raises(ValueError):
            ble_protocol.parse_button_pressed(bytes([0, 5, ord("A"), ord("B")]))

    def test_parser_rejects_empty_payload(self):
        with pytest.raises(ValueError):
            ble_protocol.parse_button_pressed(b"")
