"""Static analysis helpers for profile files — flags shell commands that
contain tokens commonly associated with download-and-execute attacks. The
warning is advisory: a hit does not prove malicious intent, but the user
should review before launching."""
from __future__ import annotations
from typing import Iterable

# Token list lifted from v0.2.3 hardening sweep. Case-insensitive match.
RISKY_COMMAND_TOKENS: tuple[str, ...] = (
    "powershell", "pwsh", "cmd /c", "cmd.exe /c",
    "curl ", "iwr ", "irm ", "wget ",
    "Invoke-Expression", "iex",
    "bitsadmin", "certutil", "reg add", "reg delete",
    "rundll32", "mshta", "regsvr32",
)


def collect_risky_commands(profiles: Iterable[dict]) -> list[tuple[str, str, str]]:
    """Return ``(profile_name, key_id, command)`` for every key whose command
    string contains any token in :data:`RISKY_COMMAND_TOKENS`. Case-insensitive
    substring match. Empty / missing commands are skipped silently.
    """
    flagged: list[tuple[str, str, str]] = []
    for profile in profiles:
        pname = profile.get("name", "?")
        for key_id, key_data in (profile.get("keys") or {}).items():
            if not isinstance(key_data, dict):
                continue
            cmd = key_data.get("command", "") or ""
            if not isinstance(cmd, str) or not cmd.strip():
                continue
            lowered = cmd.lower()
            if any(tok.lower() in lowered for tok in RISKY_COMMAND_TOKENS):
                flagged.append((pname, str(key_id), cmd))
    return flagged
