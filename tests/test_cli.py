"""Check actual console output without opening station devices or connections."""

from pathlib import Path
import subprocess
import sys
import unittest

from cli import ConfigError


class ConsoleErrors(unittest.TestCase):
    def run_error(self, exception):
        tools = Path(__file__).resolve().parents[1] / "tools"
        return subprocess.run(
            [
                sys.executable,
                "-c",
                f"import sys; sys.path.insert(0, {str(tools)!r})\n"
                "from cli import ConfigError, UserError, run_cli\n"
                "def main():\n"
                "    try:\n"
                "        raise OSError('internal context')\n"
                "    except OSError as cause:\n"
                f"        raise {exception} from cause\n"
                "run_cli(main)\n",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_expected_errors_show_the_action_without_a_traceback_or_cause(self):
        for kind in ("UserError", "ConfigError"):
            with self.subTest(kind=kind):
                result = self.run_error(
                    f"{kind}('Fix this setting.\\nRun mise run config.')"
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertEqual(
                    result.stderr,
                    "Error: Fix this setting.\nRun mise run config.\n",
                )

    def test_unexpected_errors_keep_their_traceback_and_context(self):
        # An ordinary RuntimeError must not be mistaken for an operator error.
        result = self.run_error("RuntimeError('unexpected bug')")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Traceback (most recent call last):", result.stderr)
        self.assertIn("RuntimeError: unexpected bug", result.stderr)
        self.assertIn("internal context", result.stderr)

    def test_existing_exit_codes_and_messages_are_preserved(self):
        for exception, code, message in (
            ("SystemExit(0)", 0, ""),
            ("SystemExit(7)", 7, ""),
            ("SystemExit('Station already running')", 1, "Station already running\n"),
        ):
            with self.subTest(exception=exception):
                result = self.run_error(exception)
                self.assertEqual(result.returncode, code)
                self.assertEqual(result.stderr, message)

    def test_configuration_errors_remain_value_errors_for_callers(self):
        self.assertIsInstance(ConfigError("bad setting"), ValueError)
