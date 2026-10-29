import unittest
from unittest.mock import MagicMock, patch

from qk4_cat import native_power, wait_for_receive


class RadioReadback(unittest.TestCase):
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

    def test_reads_radio_selected_power_without_writing_or_limiting_it(self):
        for frame in (b"PC050H", b"PC100H", b"PC051L", b"PC000L", b"PC050X"):
            cat = MagicMock()
            cat.recv.side_effect = [frame[:3], frame[3:] + b";"]
            with (
                self.subTest(frame=frame),
                patch("socket.create_connection") as connect,
            ):
                connect.return_value.__enter__.return_value = cat
                self.assertEqual(native_power(), frame)
            cat.sendall.assert_called_once_with(b"PC;")
