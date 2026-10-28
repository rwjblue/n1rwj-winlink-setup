import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch

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

    def test_native_k4_power_preserves_tenths_and_handles_tcp_fragments(self):
        cat = MagicMock()
        cat.recv.side_effect = [b"PC0", b"50L;"]
        with patch("socket.create_connection") as connect:
            connect.return_value.__enter__.return_value = cat
            self.assertEqual(tx_test.native_power(b"PC050L"), b"PC050L")
        self.assertEqual(
            [call.args[0] for call in cat.sendall.call_args_list], [b"PC050L;", b"PC;"]
        )

    def test_k3_style_power_frame_is_rejected_before_connection(self):
        with (
            patch("socket.create_connection") as connect,
            self.assertRaises(ValueError),
        ):
            tx_test.native_power(b"PC0500")
        connect.assert_not_called()
