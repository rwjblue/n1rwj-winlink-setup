import unittest
from unittest.mock import MagicMock, patch

from qk4_cat import require_five_watt_limit, wait_for_receive


class PowerLimit(unittest.TestCase):
    def test_unkey_readback_polls_past_initial_transmit_state(self):
        cat = MagicMock()
        cat.recv.side_effect = [b"TQ1;", b"TQ", b"0;"]
        with patch("socket.create_connection") as connect, patch("qk4_cat.time.sleep"):
            connect.return_value.__enter__.return_value = cat
            wait_for_receive(request_rx=True)
        self.assertEqual(cat.sendall.call_args_list[0].args[0], b"RX;")
        self.assertEqual(cat.sendall.call_count, 4)

    def test_unkey_readback_fails_on_connection_close(self):
        cat = MagicMock()
        cat.recv.return_value = b""
        with (
            patch("socket.create_connection") as connect,
            self.assertRaises(RuntimeError),
        ):
            connect.return_value.__enter__.return_value = cat
            wait_for_receive()

    def test_accepts_only_positive_qrp_settings_at_or_below_five_watts(self):
        for frame, watts in [(b"PC050L", 5), (b"PC001L", 0.1)]:
            with patch("qk4_cat.native_power", return_value=frame):
                self.assertEqual(require_five_watt_limit(), watts)
        for frame in [b"PC051L", b"PC075H", b"PC000L", b"PC050X"]:
            with (
                patch("qk4_cat.native_power", return_value=frame),
                self.assertRaises(RuntimeError),
            ):
                require_five_watt_limit()
