"""Tests for the rotating-log keep-alive filter (v0.2.3)."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Importing `main` instantiates PyQt5 widgets at import time? No — the module
# only defines classes; `BLEDeckGUI()` runs in `main()`. Importing is safe.
from main import _KeepAliveLogFilter


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 0, msg, (), None)


class TestKeepAliveLogFilter:
    def setup_method(self):
        self.f = _KeepAliveLogFilter()

    def test_emoji_ping_dropped(self):
        assert not self.f.filter(_record("🏓 Sending ping (last response: 5s ago)"))

    def test_emoji_pong_dropped(self):
        assert not self.f.filter(_record("🏓 Ping response received"))

    def test_hex_tag_ping_dropped(self):
        assert not self.f.filter(_record("→ aa010000 [PING]"))

    def test_hex_tag_pong_dropped(self):
        assert not self.f.filter(_record("← aa810000 [PONG]"))

    def test_keep_alive_word_dropped(self):
        assert not self.f.filter(_record("KEEP_ALIVE roundtrip"))
        assert not self.f.filter(_record("Pong received"))
        assert not self.f.filter(_record("Ping sent"))

    def test_unrelated_messages_pass(self):
        assert self.f.filter(_record("📁 Profile changed"))
        assert self.f.filter(_record("🔋 Battery: 75%"))
        assert self.f.filter(_record("→ aa040005 05ff000032 [RGB_KEY]"))
        assert self.f.filter(_record("Connected to 11:22:33:44:55:66"))
