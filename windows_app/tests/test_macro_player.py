"""Tests for macro_player — anchor resolution, key safety guard, playback.

Pure logic + mocked pynput/win32, no GUI or hardware. Covers the README
headline feature (window-relative playback survives window moves) and the
_resolve_key safety guard that rejects tampered multi-character macro keys.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import macro_player
from macro_models import ClickStep, KeyStep, SleepStep
from pynput.keyboard import Key


# --- _resolve_key ---------------------------------------------------------

def test_resolve_key_named_returns_enum():
    assert macro_player._resolve_key("enter") is Key.enter


def test_resolve_key_named_is_case_insensitive():
    assert macro_player._resolve_key("ENTER") is Key.enter


def test_resolve_key_single_char_passthrough():
    assert macro_player._resolve_key("a") == "a"


def test_resolve_key_rejects_multichar_literal():
    # safety guard: a tampered macro must not type a literal string
    with pytest.raises(ValueError):
        macro_player._resolve_key("rm -rf")


def test_resolve_key_rejects_empty_string():
    with pytest.raises(ValueError):
        macro_player._resolve_key("")


# --- _resolve_anchor -------------------------------------------------------

def test_resolve_anchor_abs_returns_none():
    assert macro_player._resolve_anchor("abs") is None
    assert macro_player._resolve_anchor("") is None


@patch("macro_player.find_window_by_title", return_value=(100, 200, 50, 50))
def test_resolve_anchor_window_origin(mock_find):
    assert macro_player._resolve_anchor("window:Notepad") == (100, 200)


@patch("macro_player.find_window_by_title", return_value=None)
def test_resolve_anchor_window_missing_falls_back_absolute(mock_find):
    assert macro_player._resolve_anchor("window:Ghost") is None


@patch("macro_player.get_monitor_rect", return_value=(1920, 0, 1920, 1080))
def test_resolve_anchor_monitor_origin(mock_mon):
    assert macro_player._resolve_anchor("monitor:1") == (1920, 0)


def test_resolve_anchor_monitor_bad_index_returns_none():
    assert macro_player._resolve_anchor("monitor:x") is None


# --- play() ----------------------------------------------------------------

@patch("macro_player.MouseController")
@patch("macro_player.KeyboardController")
@patch("macro_player._resolve_anchor", return_value=(100, 200))
def test_play_click_applies_anchor_offset(mock_anchor, mock_kb, mock_mouse):
    mouse = mock_mouse.return_value
    macro_player.play([ClickStep(x=10, y=20, button="left", relative_to="window:X")])
    assert mouse.position == (110, 220)
    mouse.click.assert_called_once()


@patch("macro_player.MouseController")
@patch("macro_player.KeyboardController")
@patch("macro_player._resolve_anchor", return_value=None)
def test_play_click_absolute_no_offset(mock_anchor, mock_kb, mock_mouse):
    mouse = mock_mouse.return_value
    macro_player.play([ClickStep(x=10, y=20, button="left", relative_to="abs")])
    assert mouse.position == (10, 20)


@patch("macro_player.MouseController")
@patch("macro_player.KeyboardController")
def test_play_key_modifier_press_release_order(mock_kb, mock_mouse):
    keyboard = mock_kb.return_value
    macro_player.play([KeyStep(key="c", modifiers=("ctrl",))])
    # modifier pressed before key, released after key
    order = [c[0] for c in keyboard.method_calls]
    assert order == ["press", "press", "release", "release"]
    assert keyboard.method_calls[0].args == (Key.ctrl,)
    assert keyboard.method_calls[1].args == ("c",)


@patch("macro_player.time.sleep")
def test_play_sleep_uses_duration(mock_sleep):
    macro_player.play([SleepStep(duration_ms=500)])
    mock_sleep.assert_any_call(0.5)
