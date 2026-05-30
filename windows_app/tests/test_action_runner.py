"""Tests for action_runner module."""
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from action_runner import ActionRunner
from macro_models import ClickStep, KeyStep, SleepStep, macro_to_list


class TestActionRunnerCommand:
    def _make_runner(self):
        return ActionRunner()

    def test_command_dispatched(self):
        runner = self._make_runner()
        logs = []
        key_data = {"action_type": "command", "command": "notepad.exe"}
        with patch("action_runner.shutil.which", return_value="/fake/notepad.exe"), \
             patch("action_runner.Path") as mock_path, \
             patch("action_runner.subprocess.Popen") as mock_popen:
            mock_path.return_value.is_file.return_value = True
            mock_popen.return_value = MagicMock()
            runner.run(key_data, key_id=0, profile_index=0, log_fn=logs.append)
            time.sleep(0.2)
        assert any("notepad.exe" in m for m in logs)

    def test_empty_command_logs_warning(self):
        runner = self._make_runner()
        logs = []
        runner.run({"action_type": "command", "command": ""}, 0, 0, logs.append)
        assert any("No command" in m for m in logs)

    def test_missing_action_type_defaults_to_command(self):
        runner = self._make_runner()
        logs = []
        with patch("action_runner.shutil.which", return_value="/fake/calc.exe"), \
             patch("action_runner.Path") as mock_path, \
             patch("action_runner.subprocess.Popen") as mock_popen:
            mock_path.return_value.is_file.return_value = True
            mock_popen.return_value = MagicMock()
            runner.run({"command": "calc.exe"}, key_id=1, profile_index=0, log_fn=logs.append)
            time.sleep(0.2)
        assert any("calc.exe" in m for m in logs)

    def test_reentrancy_guard_command(self):
        runner = self._make_runner()
        logs = []
        # Force a key into the active set manually
        guard = (0, 0)
        with runner._lock:
            runner._active.add(guard)
        runner.run({"action_type": "command", "command": "x"}, 0, 0, logs.append)
        assert any("still running" in m for m in logs)
        # Cleanup
        with runner._lock:
            runner._active.discard(guard)

    def test_command_popen_exception_logged(self):
        runner = self._make_runner()
        logs = []
        with patch("action_runner.shutil.which", return_value="/fake/bad.exe"), \
             patch("action_runner.Path") as mock_path, \
             patch("action_runner.subprocess.Popen", side_effect=OSError("boom")):
            mock_path.return_value.is_file.return_value = True
            runner.run({"command": "bad"}, 0, 0, logs.append)
            time.sleep(0.2)
        assert any("Command failed" in m for m in logs)

    def test_unresolvable_executable_logs_not_found(self):
        runner = self._make_runner()
        logs = []
        with patch("action_runner.shutil.which", return_value=None), \
             patch("action_runner.Path") as mock_path, \
             patch("action_runner.subprocess.Popen") as mock_popen:
            mock_path.return_value.is_file.return_value = False
            runner.run({"command": "nonexistent.exe"}, 0, 0, logs.append)
            time.sleep(0.2)
            mock_popen.assert_not_called()
        assert any("Executable not found" in m for m in logs)

    def test_shell_metacharacters_not_expanded(self):
        """Critical: tampered profiles.json must not chain commands via shell ops."""
        runner = self._make_runner()
        logs = []
        # `calc & del *.*` — under shell=True this would chain; under shell=False
        # the entire string is tokenized and resolver looks up "calc" as exe.
        with patch("action_runner.shutil.which", return_value="/fake/calc.exe"), \
             patch("action_runner.Path") as mock_path, \
             patch("action_runner.subprocess.Popen") as mock_popen:
            mock_path.return_value.is_file.return_value = True
            mock_popen.return_value = MagicMock()
            runner.run({"command": "calc & del *.*"}, 0, 0, logs.append)
            time.sleep(0.2)
            args, kwargs = mock_popen.call_args
            argv = args[0]
            # Must call as argv list, not shell string
            assert isinstance(argv, list)
            assert kwargs.get("shell") is False
            # `&` and `del` must appear as literal args, not as a chained command
            assert "&" in argv
            assert "del" in argv


class TestActionRunnerMacro:
    def test_macro_dispatched_in_thread(self):
        runner = ActionRunner()
        logs = []
        steps = [SleepStep(duration_ms=10)]
        key_data = {"action_type": "macro", "macro": macro_to_list(steps)}

        with patch("action_runner.macro_player.play") as mock_play:
            runner.run(key_data, key_id=2, profile_index=1, log_fn=logs.append)
            # Give thread a moment to run
            time.sleep(0.2)

        mock_play.assert_called_once()
        called_steps = mock_play.call_args[0][0]
        assert called_steps == steps

    def test_macro_guard_released_after_thread(self):
        runner = ActionRunner()
        steps = [SleepStep(duration_ms=10)]
        key_data = {"action_type": "macro", "macro": macro_to_list(steps)}
        guard = (0, 3)

        with patch("action_runner.macro_player.play"):
            runner.run(key_data, key_id=3, profile_index=0, log_fn=lambda m: None)
            time.sleep(0.2)

        with runner._lock:
            assert guard not in runner._active

    def test_empty_macro_logs_warning(self):
        runner = ActionRunner()
        logs = []
        runner.run({"action_type": "macro", "macro": []}, 0, 0, logs.append)
        assert any("No macro steps" in m for m in logs)

    def test_macro_error_logged(self):
        runner = ActionRunner()
        logs = []
        steps = [SleepStep(duration_ms=10)]
        key_data = {"action_type": "macro", "macro": macro_to_list(steps)}

        with patch("action_runner.macro_player.play", side_effect=RuntimeError("boom")):
            runner.run(key_data, key_id=0, profile_index=0, log_fn=logs.append)
            time.sleep(0.2)

        assert any("Macro error" in m for m in logs)

    def test_reentrancy_guard_macro(self):
        runner = ActionRunner()
        logs = []
        guard = (1, 5)
        with runner._lock:
            runner._active.add(guard)
        steps = [SleepStep(10)]
        runner.run({"action_type": "macro", "macro": macro_to_list(steps)},
                   key_id=5, profile_index=1, log_fn=logs.append)
        assert any("still running" in m for m in logs)
        with runner._lock:
            runner._active.discard(guard)
