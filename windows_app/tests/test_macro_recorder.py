"""Tests for macro_recorder.MacroRecorder idle-auto-stop (v0.2.3)."""
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import macro_recorder
from macro_recorder import MacroRecorder


@pytest.fixture
def fast_idle(monkeypatch):
    """Shrink the auto-stop window so tests run in ~100 ms."""
    monkeypatch.setattr(macro_recorder, "_IDLE_AUTOSTOP_SECONDS", 0.05)


@pytest.fixture
def stubbed_listeners(monkeypatch):
    """Replace pynput listeners with no-op mocks; they would otherwise grab
    real OS-wide input hooks for the duration of the test run."""
    monkeypatch.setattr(macro_recorder, "MouseListener", MagicMock())
    monkeypatch.setattr(macro_recorder, "KeyboardListener", MagicMock())


def test_idle_timeout_fires_on_done(fast_idle, stubbed_listeners):
    done = threading.Event()
    captured: list = []
    rec = MacroRecorder(on_done=lambda steps: (captured.append(steps), done.set()))
    rec.start()
    assert done.wait(0.5), "auto-stop never fired"
    assert isinstance(captured[0], list)


def test_idle_timer_resets_on_event(fast_idle, stubbed_listeners):
    done = threading.Event()
    rec = MacroRecorder(on_done=lambda _steps: done.set())
    rec.start()
    time.sleep(0.03)
    rec._reset_idle_timer()  # simulated activity
    time.sleep(0.03)         # would have fired without reset
    assert not done.is_set(), "idle timer should have been reset"
    assert done.wait(0.1), "timer never re-fired after the new window"


def test_explicit_stop_cancels_idle_timer(stubbed_listeners):
    rec = MacroRecorder(on_done=lambda _steps: None)
    rec.start()
    rec.stop()
    rec.stop()  # double-stop must not crash, must not double-fire on_done


def test_stop_invokes_on_done_once(stubbed_listeners):
    calls = 0
    def _cb(_):
        nonlocal calls
        calls += 1
    rec = MacroRecorder(on_done=_cb)
    rec.start()
    rec.stop()
    rec.stop()  # second call is a no-op
    assert calls == 1
