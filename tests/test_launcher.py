"""Lifecycle checks for the launcher, independent of AI weights and GPU."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import launcher


class LaunchLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix='jingliu-launch-')
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)
        self.config = {'python': sys.executable, 'ports': {'studio': 17861, 'comfy': 18193, 'ollama': 11435},
                       'comfy': str(self.runtime), 'ffmpeg_dir': '', 'ollama_binary': None, 'region': 'CN'}

    def expected(self):
        return {'app': 'jingliu', 'workspace': launcher.workspace_id(self.runtime / 'studio-data')}

    def test_repeat_launch_reuses_only_matching_workspace(self):
        with patch.object(launcher, 'identity', return_value=self.expected()), \
                patch.object(launcher.webbrowser, 'open') as browser, \
                patch.object(launcher.subprocess, 'Popen') as spawn:
            launcher.run(self.runtime, self.config)
        browser.assert_called_once_with('http://127.0.0.1:17861')
        spawn.assert_not_called()

    def test_foreign_port_is_not_opened_or_killed(self):
        with patch.object(launcher, 'identity', return_value={'app': 'other'}), \
                patch.object(launcher.installer, 'check_port', side_effect=RuntimeError('busy')), \
                patch.object(launcher.subprocess, 'Popen') as spawn, \
                patch.object(launcher.installer, 'stop_owned') as stop:
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                launcher.run(self.runtime, self.config)
        spawn.assert_not_called()
        stop.assert_not_called()

    def test_failed_start_cleans_up_only_owned_process(self):
        process = MagicMock()
        with patch.object(launcher, 'identity', return_value=None), \
                patch.object(launcher.installer, 'check_port'), \
                patch.object(launcher.subprocess, 'Popen', return_value=process), \
                patch.object(launcher, 'wait_ready', side_effect=RuntimeError('early exit')), \
                patch.object(launcher.installer, 'stop_owned') as stop:
            with self.assertRaisesRegex(RuntimeError, 'early exit'):
                launcher.run(self.runtime, self.config, browser=False)
        stop.assert_called_once_with(process)

    def test_optional_writer_failure_does_not_close_editor(self):
        process = MagicMock()
        process.poll.return_value = 0
        with patch.object(launcher, 'identity', return_value=None), \
                patch.object(launcher.installer, 'check_port'), \
                patch.object(launcher.subprocess, 'Popen', return_value=process), \
                patch.object(launcher, 'wait_ready'), \
                patch.object(launcher.installer, 'start_ollama', side_effect=RuntimeError('writer busy')), \
                patch.object(launcher.webbrowser, 'open') as browser, \
                patch.object(launcher.installer, 'stop_owned') as stop:
            launcher.run(self.runtime, self.config)
        browser.assert_called_once()
        stop.assert_called_once_with(process)

    def test_os_lock_prevents_duplicate_and_stop_never_guesses_pid(self):
        lock = self.runtime / '.launcher.lock'
        with launcher.instance_lock(lock) as owner:
            self.assertTrue(owner)
            code = ('import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); '
                    'import launcher; launcher.request_stop(Path(sys.argv[2]))')
            subprocess.run([sys.executable, '-B', '-c', code, str(Path(launcher.__file__).parent),
                            str(self.runtime)], check=True, capture_output=True, timeout=15)
            self.assertTrue((self.runtime / '.launcher-stop').exists())
        (self.runtime / '.launcher-stop').unlink()
        launcher.request_stop(self.runtime)
        self.assertFalse((self.runtime / '.launcher-stop').exists())
        with launcher.instance_lock(lock) as owner:
            self.assertTrue(owner)

    def test_workspace_id_separates_project_directories(self):
        self.assertNotEqual(launcher.workspace_id(self.runtime / 'a'), launcher.workspace_id(self.runtime / 'b'))


if __name__ == '__main__':
    unittest.main()
