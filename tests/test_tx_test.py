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

