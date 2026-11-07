import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from panel_schedule import ensure_schedule

class ScheduleTests(unittest.TestCase):
    def test_path_passed_as_data_and_no_immediate_run(self):
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / "TradeSeaAsia.exe"
            exe.touch()
            runner = Mock(return_value=SimpleNamespace(returncode=0, stderr=''))
            ensure_schedule(exe, runner)
            args, kwargs = runner.call_args
            script = args[0][-1]
            self.assertEqual(kwargs['env']['TRADESEA_SCHEDULE_EXE'], str(exe.resolve()))
            self.assertNotIn(str(exe), script)
            self.assertNotIn('Start-ScheduledTask', script)
            self.assertIn("yyyy-MM-ddTHH:mm:ss", script)
            self.assertIn('-LogonType Interactive -RunLevel Limited', script)
            self.assertIn('New-ScheduledTaskSettingsSet -WakeToRun', script)

    def test_windows_rejection_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / 'TradeSeaAsia.exe'
            exe.touch()
            with self.assertRaisesRegex(RuntimeError, 'Access denied'):
                ensure_schedule(exe, Mock(return_value=SimpleNamespace(returncode=1, stderr='Access denied')))

    def test_missing_executable_does_not_register(self):
        runner = Mock()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RuntimeError):
                ensure_schedule(Path(folder) / 'missing.exe', runner)
        runner.assert_not_called()
