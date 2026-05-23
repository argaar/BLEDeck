"""Immutable data model for macro steps and JSON serialization."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ClickStep:
    x: int
    y: int
    button: str = "left"
    # Anchor for coordinate resolution at playback:
    #   "window:<title>"  — relative to top-left of the named window
    #   "monitor:<N>"     — relative to monitor N left-top (taskbar / desktop)
    #   "abs" or ""       — absolute screen coordinates
    relative_to: str = ""


@dataclass(frozen=True)
class KeyStep:
    key: str
    modifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class SleepStep:
    duration_ms: int


MacroStep = ClickStep | KeyStep | SleepStep


def step_description(step: MacroStep) -> str:
    if isinstance(step, ClickStep):
        rt = step.relative_to
        if rt.startswith("window:"):
            title = rt[7:]
            anchor = f"[{title[:24]}]" if title else "[foreground]"
        elif rt.startswith("monitor:"):
            anchor = f"[monitor {rt[8:]}]"
        else:
            anchor = "[abs]"
        return f"Click {step.button} @ ({step.x}, {step.y}) {anchor}"
    if isinstance(step, KeyStep):
        parts = list(step.modifiers) + [step.key]
        return "Key: " + "+".join(parts)
    if isinstance(step, SleepStep):
        return f"Sleep {step.duration_ms}ms"
    return repr(step)


def step_to_dict(step: MacroStep) -> dict[str, Any]:
    if isinstance(step, ClickStep):
        return {"type": "click", "x": step.x, "y": step.y,
                "button": step.button, "relative_to": step.relative_to}
    if isinstance(step, KeyStep):
        return {"type": "key", "key": step.key,
                "modifiers": list(step.modifiers)}
    if isinstance(step, SleepStep):
        return {"type": "sleep", "duration_ms": step.duration_ms}
    raise TypeError(f"Unknown step type: {type(step)}")


def step_from_dict(d: dict[str, Any]) -> MacroStep:
    t = d.get("type")
    if t == "click":
        if "relative_to" in d:
            relative_to = d["relative_to"]
        elif d.get("relative", False):
            relative_to = "window:"  # old relative=True → any foreground window
        else:
            relative_to = "abs"
        return ClickStep(
            x=int(d["x"]), y=int(d["y"]),
            button=d.get("button", "left"),
            relative_to=relative_to,
        )
    if t == "key":
        return KeyStep(
            key=d["key"],
            modifiers=tuple(d.get("modifiers", [])),
        )
    if t == "sleep":
        return SleepStep(duration_ms=int(d["duration_ms"]))
    raise ValueError(f"Unknown step type: {t!r}")


def macro_to_list(steps: list[MacroStep]) -> list[dict[str, Any]]:
    return [step_to_dict(s) for s in steps]


def macro_from_list(data: list[dict[str, Any]]) -> list[MacroStep]:
    return [step_from_dict(d) for d in data]
