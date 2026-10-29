"""Exercise task argument parsing with inert stand-ins for all station tools."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("mise"), "mise is required for task argument checks")
class MiseTaskArguments(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / "mise.toml").write_text("")
        shutil.copytree(ROOT / "mise/tasks", self.root / "mise/tasks")
        # These record argv instead of importing station code, opening devices,
        # changing preferences or keying a radio, even for --execute tests.
        for relative in (".venv/bin/python", "bin/pat"):
            tool = self.root / relative
            tool.parent.mkdir(parents=True, exist_ok=True)
            tool.write_text(
                f"#!{sys.executable}\n"
                "import json, sys\n"
                "print(json.dumps(sys.argv[1:]))\n"
            )
            tool.chmod(0o755)
        self.env = os.environ | {
            "MISE_TRUSTED_CONFIG_PATHS": str(self.root),
            "MISE_TASK_OUTPUT": "interleave",
        }

    def run_task(self, task, *args):
        return subprocess.run(
            [
                "mise",
                "-C",
                str(self.root),
                "run",
                "--skip-deps",
                "--skip-tools",
                "--quiet",
                task,
                *args,
            ],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_arguments_reach_station_tools_without_a_separator(self):
        cases = [
            ("start", [], ["tools/station.py", "start", "--background"]),
            (
                "start",
                ["--receive-only"],
                ["tools/station.py", "start", "--background"],
            ),
            ("receive-check", ["--dial-khz", "7100"], ["tools/receive_check.py"]),
            ("audio", ["devices"], ["tools/audio.py"]),
            (
                "audio",
                [
                    "record",
                    "--seconds",
                    "3.5",
                    "--direction",
                    "rx",
                    "--output",
                    "recordings/receive sample.wav",
                ],
                ["tools/audio.py"],
            ),
            (
                "configure-qk4",
                [
                    "--profile",
                    "2",
                    "--dry-run",
                    "--restore",
                    "backups/saved settings.plist",
                ],
                ["tools/qk4_settings.py"],
            ),
            (
                "calibrate-audio",
                [
                    "--execute",
                    "--peaks",
                    "0.2",
                    "0.3",
                    "0.35",
                    "--dial-khz",
                    "7101",
                    "--signal",
                    "cw",
                ],
                ["tools/calibrate_audio.py"],
            ),
            (
                "link-test",
                [
                    "varahf:///KB8AY?bw=2750&freq=7100",
                    "--seconds",
                    "30",
                    "--execute",
                    "--approved-transmit",
                ],
                ["tools/link_test.py"],
            ),
            (
                "tx-test",
                [
                    "--execute",
                    "--approved-transmit",
                    "--antenna-confirmed",
                    "--amplifier-bypassed",
                    "--dial-khz",
                    "7101",
                ],
                ["tools/tx_test.py"],
            ),
            (
                "tx-test",
                [
                    "--execute",
                    "--radio-test-mode",
                    "--dummy-load-confirmed",
                    "--signal",
                    "vara-connect",
                    "--audio-peak",
                    "0.35",
                ],
                ["tools/tx_test.py"],
            ),
            ("tx-test", ["--unkey"], ["tools/tx_test.py"]),
            ("pat", ["rmslist", "--mode", "varahf", "--band", "20m"], []),
            ("pat", ["--help"], []),
            ("pat", ["--version"], []),
        ]
        for task, args, prefix in cases:
            with self.subTest(task=task, args=args):
                result = self.run_task(task, *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("invalid usage spec", result.stderr.lower())
                self.assertEqual(json.loads(result.stdout), prefix + args)

    def test_task_help_describes_arguments_without_running_station_tools(self):
        for task, flag in (
            ("start", "--receive-only"),
            ("receive-check", "--dial-khz"),
            ("audio", "--direction"),
            ("configure-qk4", "--restore"),
            ("calibrate-audio", "--peaks"),
            ("link-test", "--seconds"),
            ("tx-test", "--audio-peak"),
        ):
            with self.subTest(task=task):
                result = self.run_task(task, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Usage:", result.stdout)
                self.assertIn(flag, result.stdout)

    def test_invalid_flags_and_choices_are_rejected_before_running_tools(self):
        for task, args in (
            ("start", ["--recieve-only"]),
            ("audio", ["record", "--direction", "invalid"]),
            ("calibrate-audio", ["--signal", "invalid"]),
            ("tx-test", ["--signal", "invalid"]),
        ):
            with self.subTest(task=task):
                result = self.run_task(task, *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
