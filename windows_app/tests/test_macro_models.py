"""Tests for macro_models module."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from macro_models import (
    ClickStep, KeyStep, SleepStep,
    step_description, step_to_dict, step_from_dict,
    macro_to_list, macro_from_list,
)


class TestClickStep:
    def test_immutable(self):
        step = ClickStep(x=10, y=20)
        try:
            step.x = 99
            assert False, "Should have raised"
        except (AttributeError, TypeError):
            pass

    def test_defaults(self):
        step = ClickStep(x=0, y=0)
        assert step.button == "left"
        assert step.relative_to == ""

    def test_description_window_anchor(self):
        d = step_description(ClickStep(x=100, y=200, button="right", relative_to="window:Calculator"))
        assert "100" in d and "200" in d and "right" in d and "Calculator" in d

    def test_description_foreground_anchor(self):
        d = step_description(ClickStep(x=10, y=20, relative_to="window:"))
        assert "foreground" in d

    def test_description_absolute(self):
        d = step_description(ClickStep(x=50, y=60, relative_to="abs"))
        assert "abs" in d

    def test_description_monitor_anchor(self):
        d = step_description(ClickStep(x=10, y=20, relative_to="monitor:1"))
        assert "monitor" in d and "1" in d

    def test_description_empty_relative_to_shows_abs(self):
        d = step_description(ClickStep(x=5, y=5))
        assert "abs" in d

    def test_roundtrip_abs(self):
        step = ClickStep(x=123, y=456, button="middle", relative_to="abs")
        assert step_from_dict(step_to_dict(step)) == step

    def test_roundtrip_window_anchor(self):
        step = ClickStep(x=10, y=20, relative_to="window:Notepad")
        assert step_from_dict(step_to_dict(step)) == step

    def test_roundtrip_monitor_anchor(self):
        step = ClickStep(x=30, y=40, relative_to="monitor:0")
        assert step_from_dict(step_to_dict(step)) == step


class TestKeyStep:
    def test_immutable(self):
        step = KeyStep(key="a")
        try:
            step.key = "b"
            assert False, "Should have raised"
        except (AttributeError, TypeError):
            pass

    def test_defaults(self):
        step = KeyStep(key="enter")
        assert step.modifiers == ()

    def test_description_no_modifiers(self):
        assert step_description(KeyStep(key="a")) == "Key: a"

    def test_description_with_modifiers(self):
        d = step_description(KeyStep(key="c", modifiers=("ctrl",)))
        assert d == "Key: ctrl+c"

    def test_description_multi_modifier(self):
        d = step_description(KeyStep(key="s", modifiers=("ctrl", "shift")))
        assert "ctrl" in d and "shift" in d and "s" in d

    def test_roundtrip(self):
        step = KeyStep(key="v", modifiers=("ctrl",))
        assert step_from_dict(step_to_dict(step)) == step

    def test_roundtrip_no_modifiers(self):
        step = KeyStep(key="enter")
        assert step_from_dict(step_to_dict(step)) == step


class TestSleepStep:
    def test_immutable(self):
        step = SleepStep(duration_ms=500)
        try:
            step.duration_ms = 999
            assert False, "Should have raised"
        except (AttributeError, TypeError):
            pass

    def test_description(self):
        assert step_description(SleepStep(duration_ms=250)) == "Sleep 250ms"

    def test_roundtrip(self):
        step = SleepStep(duration_ms=1000)
        assert step_from_dict(step_to_dict(step)) == step


class TestStepFromDict:
    def test_unknown_type_raises(self):
        import pytest
        with pytest.raises(ValueError, match="Unknown step type"):
            step_from_dict({"type": "hover", "x": 0, "y": 0})

    def test_click_no_anchor_defaults_to_abs(self):
        step = step_from_dict({"type": "click", "x": 5, "y": 10})
        assert step == ClickStep(x=5, y=10, button="left", relative_to="abs")

    def test_click_with_relative_to(self):
        step = step_from_dict({"type": "click", "x": 5, "y": 10, "relative_to": "window:Calc"})
        assert step == ClickStep(x=5, y=10, relative_to="window:Calc")

    def test_click_with_monitor_anchor(self):
        step = step_from_dict({"type": "click", "x": 5, "y": 10, "relative_to": "monitor:2"})
        assert step.relative_to == "monitor:2"

    def test_key_empty_modifiers(self):
        step = step_from_dict({"type": "key", "key": "tab"})
        assert step == KeyStep(key="tab", modifiers=())


class TestMacroListRoundtrip:
    def test_empty(self):
        assert macro_from_list(macro_to_list([])) == []

    def test_mixed_steps(self):
        steps = [
            ClickStep(x=10, y=20, button="left", relative_to="window:MyApp"),
            KeyStep(key="c", modifiers=("ctrl",)),
            SleepStep(duration_ms=300),
        ]
        result = macro_from_list(macro_to_list(steps))
        assert result == steps

    def test_preserves_order(self):
        steps = [SleepStep(100), SleepStep(200), SleepStep(300)]
        result = macro_from_list(macro_to_list(steps))
        assert [s.duration_ms for s in result] == [100, 200, 300]

    def test_mixed_anchors(self):
        steps = [
            ClickStep(x=0, y=0, relative_to="abs"),
            ClickStep(x=5, y=5, relative_to="window:Notepad"),
            ClickStep(x=10, y=10, relative_to="monitor:1"),
        ]
        result = macro_from_list(macro_to_list(steps))
        assert result == steps
