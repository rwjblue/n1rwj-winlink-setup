import contextlib
import io
import unittest
from unittest.mock import patch

import tx_test


class TransmitPreparation(unittest.TestCase):
    def test_default_dry_run_opens_no_devices(self):
        with (
            patch("sys.argv", ["tx_test"]),
            patch("socket.create_connection") as connect,
            patch("sounddevice.OutputStream") as stream,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            tx_test.main()
        connect.assert_not_called()
        stream.assert_not_called()

    def test_off_air_result_requires_logical_tx_and_zero_forward_meter_readback(self):
        result = tx_test.verify_off_air_telemetry(
            [{"reply": "TQ1;TM000000000010;TQ0;"}]
        )
        self.assertTrue(result["forward_power_zero"])
        for reply in ("TQ0;TM000000000010;", "TQ1;", "TQ1;TM000000050010;"):
            with self.subTest(reply=reply), self.assertRaises(RuntimeError):
                tx_test.verify_off_air_telemetry([{"reply": reply}])

    def test_execution_without_approval_opens_no_devices(self):
        with (
            patch("sys.argv", ["tx_test", "--execute"]),
            patch("socket.create_connection") as connect,
            patch("sounddevice.OutputStream") as stream,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            tx_test.main()
        connect.assert_not_called()
        stream.assert_not_called()

    def test_unconfirmed_hardware_test_mode_never_opens_radio_or_audio(self):
        with (
            patch("sys.argv", ["tx_test", "--execute", "--radio-test-mode"]),
            patch(
                "tx_test.require_radio_test_mode",
                side_effect=RuntimeError("no TX TEST"),
            ),
            patch("socket.create_connection") as connect,
            patch("sounddevice.OutputStream") as stream,
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "no TX TEST"),
        ):
            tx_test.main()
        connect.assert_not_called()
        stream.assert_not_called()
