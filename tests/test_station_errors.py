"""Exercise supervisor failures with inert processes and fake QK4 preferences."""

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from cli import UserError
import station


class BackgroundStartupErrors(unittest.TestCase):
    def run_failure(self, body, *, background=True):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        logs = root / "logs"
        logs.mkdir()
        log = logs / "supervisor.log"
        log.write_text("Old startup failure: café\n")
        script = root / "supervisor.py"
        script.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            f"sys.path.insert(0, {str(Path(station.__file__).resolve().parent)!r})\n"
            "from cli import run_cli\n"
            "from qk4_settings import verify_audio_devices\n"
            "import station\n"
            f"station.LOCAL = Path({str(root)!r})\n"
            "station.__file__ = __file__\n"
            # Both the launcher and detached supervisor run this stand-in.
            # No real stack, device, CAT connection or radio command can run.
            "def fail(transmit=False):\n"
            "    assert not transmit, 'test requires receive-only mode'\n"
            + "\n".join(f"    {line}" for line in body.splitlines())
            + "\nstation.run_stack = fail\n"
            "run_cli(station.main)\n"
        )
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "start",
                "--receive-only",
                *(["--background"] if background else []),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result, log.read_text()

    def test_qk4_audio_mismatch_reaches_foreground_and_background_consoles(self):
        cfg = station.config()
        devices = [
            {
                "name": cfg["rx_device"],
                "input": False,
                "id": "rx",
                "qk4_format_supported": True,
            },
            {
                "name": cfg["tx_device"],
                "input": True,
                "id": "tx",
                "qk4_format_supported": True,
            },
        ]
        preferences = {
            "audio.speakerDevice": "built-in-output",
            "audio.micDevice": "tx",
            "audio.micGain": cfg["qk4_mic_gain"],
            "radios.1.password": "test-secret",
        }
        body = f"verify_audio_devices({preferences!r}, {devices!r})"
        for background in (False, True):
            with self.subTest(background=background):
                result, log = self.run_failure(body, background=background)
                self.assertEqual(result.returncode, 1)
                self.assertIn("Error: QK4 saved audio settings differ", result.stderr)
                self.assertIn("Speaker/output device", result.stderr)
                self.assertIn(cfg["rx_device"], result.stderr)
                self.assertIn("mise run configure-qk4", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertNotIn("Old startup failure", result.stderr)
                self.assertNotIn("test-secret", result.stderr)
                if background:
                    self.assertIn("Station startup failed", result.stderr)
                    self.assertIn("audio.speakerDevice", log)
                    self.assertNotIn("Traceback", log)

    def test_existing_preflight_exit_message_reaches_background_console(self):
        result, _ = self.run_failure("raise SystemExit('Station already running')")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Station already running", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("Old startup failure", result.stderr)

    def test_unexpected_supervisor_bug_keeps_its_traceback(self):
        result, log = self.run_failure(
            "raise RuntimeError('unexpected supervisor bug')"
        )
        self.assertEqual(result.returncode, 1)
        for output in (result.stderr, log):
            self.assertIn("Traceback (most recent call last):", output)
            self.assertIn("RuntimeError: unexpected supervisor bug", output)
        self.assertNotIn("Old startup failure", result.stderr)

    def test_exit_without_output_does_not_replay_an_older_failure(self):
        result, _ = self.run_failure("raise SystemExit(2)")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Station startup failed (2)", result.stderr)
        self.assertIn("No process output available", result.stderr)
        self.assertNotIn("Old startup failure", result.stderr)


class ChildStartupErrors(unittest.TestCase):
    def check_child_failure(self, *, dependency_exits):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        logs = root / "logs"
        logs.mkdir()
        (logs / "cat-guard.log").write_text("Old CAT failure\n")
        cfg = station.config()
        pat = root / "pat.json"
        pat.write_text(
            json.dumps(
                {
                    "varahf": {
                        "addr": "127.0.0.1:8300",
                        "rig": "qk4",
                        "ptt_ctrl": True,
                    },
                    "hamlib_rigs": {
                        "qk4": {
                            "network": "tcp",
                            "address": f"127.0.0.1:{cfg['rigctld_port']}",
                            "VFO": "",
                        }
                    },
                    "listen": ["varahf"],
                    "schedule": {},
                }
            )
        )
        guard = Mock()
        guard.poll.return_value = None
        rigctld = Mock()
        rigctld.poll.return_value = None
        guard_log = None

        def spawn(_args, **kwargs):
            nonlocal guard_log
            if guard_log is None:
                guard_log = kwargs["stdout"]
                guard_log.write(
                    "CAT guard ready\n" if dependency_exits else "Waiting for QK4\n"
                )
                guard_log.flush()
                return guard
            guard.returncode = 23
            guard.poll.return_value = 23
            guard_log.write("QK4 connection dropped\n")
            guard_log.flush()
            kwargs["stdout"].write("Unrelated rigctld output\n")
            kwargs["stdout"].flush()
            return rigctld

        with (
            patch("station.LOCAL", root),
            patch("station.pat_environment", return_value={}),
            patch("station.verify_audio_devices"),
            patch("station.configure", return_value=pat),
            patch("station.port_open", return_value=False),
            patch("station.socket.create_connection"),
            patch("station.signal.signal"),
            patch("station.time.sleep"),
            patch("station.subprocess.Popen", side_effect=spawn),
            patch("station.operating_state") as radio,
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(UserError) as error,
        ):
            station.run_stack(transmit=False)
        radio.assert_not_called()
        self.assertNotIn("Old CAT failure", str(error.exception))
        return str(error.exception), guard, rigctld

    def test_identifies_the_dependency_that_exited_and_shows_its_output(self):
        message, _, rigctld = self.check_child_failure(dependency_exits=True)
        self.assertIn("cat-guard exited (23) during startup", message)
        self.assertIn("QK4 connection dropped", message)
        self.assertNotIn("Unrelated rigctld output", message)
        rigctld.terminate.assert_called_once()
        rigctld.wait.assert_called_once_with(timeout=3)

    def test_readiness_timeout_includes_output_and_still_stops_the_child(self):
        message, guard, _ = self.check_child_failure(dependency_exits=False)
        self.assertIn("cat-guard did not become ready", message)
        self.assertIn("Waiting for QK4", message)
        guard.terminate.assert_called_once()
        guard.wait.assert_called_once_with(timeout=3)
