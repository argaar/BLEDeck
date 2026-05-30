"""Tests for simulator/cli.py REPL (v0.1.2).

Requires pytest-asyncio. If not picked up automatically, set
`asyncio_mode = "auto"` in pyproject.toml or pass `--asyncio-mode=auto`
to pytest. Tests here mark themselves explicitly via `pytestmark`, which
works in both strict and auto modes.
"""
import asyncio
import sys
from pathlib import Path
from typing import List

import pytest

# Make `simulator` importable when running pytest from project root.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from simulator import cli
from simulator._context import reset_state
from simulator.device_state import DeviceState

pytestmark = pytest.mark.asyncio


class _ScriptedInput:
    """Replace `input()` with a queue of pre-canned lines. Raises EOFError
    when exhausted so the REPL exits even if it doesn't see `q`."""

    def __init__(self, lines):
        self._lines = list(lines)

    def __call__(self, _prompt=""):
        if not self._lines:
            raise EOFError
        return self._lines.pop(0)


@pytest.fixture(autouse=True)
def _isolate():
    reset_state()
    yield


@pytest.fixture
def state():
    return DeviceState()


async def _drive(monkeypatch, state, lines) -> List[bytes]:
    """Run the REPL once with the given scripted input. Return packets sent."""
    monkeypatch.setattr("builtins.input", _ScriptedInput(lines))
    sent: List[bytes] = []

    async def _send(data: bytes) -> None:
        sent.append(data)

    await cli.run_cli(state, _send, asyncio.get_running_loop())
    return sent


async def test_quit_breaks_loop_no_packets(monkeypatch, state):
    sent = await _drive(monkeypatch, state, ["q"])
    assert sent == []


async def test_exit_alias_breaks_loop(monkeypatch, state):
    sent = await _drive(monkeypatch, state, ["exit"])
    assert sent == []


async def test_quit_alias_breaks_loop(monkeypatch, state):
    sent = await _drive(monkeypatch, state, ["quit"])
    assert sent == []


async def test_eof_breaks_loop(monkeypatch, state):
    sent = await _drive(monkeypatch, state, [])  # immediate EOF
    assert sent == []


async def test_blank_line_ignored(monkeypatch, state):
    sent = await _drive(monkeypatch, state, ["", "   ", "q"])
    assert sent == []


async def test_battery_clamps_negative(monkeypatch, state):
    sent = await _drive(monkeypatch, state, ["battery -50", "q"])
    assert state.battery_percent == -1
    assert len(sent) == 1


async def test_battery_clamps_over_100(monkeypatch, state):
    sent = await _drive(monkeypatch, state, ["battery 9999", "q"])
    assert state.battery_percent == 100
    assert len(sent) == 1


async def test_battery_at_75(monkeypatch, state):
    sent = await _drive(monkeypatch, state, ["battery 75", "q"])
    assert state.battery_percent == 75
    assert len(sent) == 1


async def test_press_rejects_multi_char(monkeypatch, state, capsys):
    sent = await _drive(monkeypatch, state, ["press 0 ABC", "q"])
    out = capsys.readouterr().out
    assert "Error" in out
    assert sent == []


async def test_press_emits_packet(monkeypatch, state):
    sent = await _drive(monkeypatch, state, ["press 0 A", "q"])
    assert len(sent) == 1


async def test_profile_rejects_out_of_range(monkeypatch, state, capsys):
    sent = await _drive(monkeypatch, state, ["profile 999", "q"])
    out = capsys.readouterr().out
    assert "Error" in out
    assert sent == []


async def test_profile_negative_rejected(monkeypatch, state, capsys):
    sent = await _drive(monkeypatch, state, ["profile -1", "q"])
    out = capsys.readouterr().out
    assert "Error" in out
    assert sent == []


async def test_profile_emits_and_updates_state(monkeypatch, state):
    sent = await _drive(monkeypatch, state, ["profile 2", "q"])
    assert state.current_profile_index == 2
    assert len(sent) == 1


async def test_help_prints_no_packet(monkeypatch, state, capsys):
    sent = await _drive(monkeypatch, state, ["help", "q"])
    out = capsys.readouterr().out
    assert "battery" in out and "press" in out
    assert sent == []


async def test_help_question_mark_alias(monkeypatch, state, capsys):
    sent = await _drive(monkeypatch, state, ["?", "q"])
    out = capsys.readouterr().out
    assert "battery" in out and "press" in out
    assert sent == []


async def test_state_prints_no_packet(monkeypatch, state, capsys):
    sent = await _drive(monkeypatch, state, ["state", "q"])
    out = capsys.readouterr().out
    assert "profile_index" in out
    assert sent == []


async def test_unknown_command_logged(monkeypatch, state, capsys):
    sent = await _drive(monkeypatch, state, ["foobar 1 2", "q"])
    out = capsys.readouterr().out
    assert "Unknown" in out
    assert sent == []


async def test_button_emits_packet(monkeypatch, state):
    sent = await _drive(monkeypatch, state, ["button macro1", "q"])
    assert len(sent) == 1
