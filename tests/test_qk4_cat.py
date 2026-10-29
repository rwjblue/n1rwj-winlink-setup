import itertools
import unittest
from unittest.mock import MagicMock, patch

from qk4_cat import (
    native_power,
    operating_state,
    restore_mode,
    select_data_a,
    wait_for_receive,
)


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

    def test_operating_state_includes_native_data_submode_and_filter(self):
        cat = MagicMock()
        cat.recv.side_effect = [b"FA00007100000;MD6;D", b"T0;BW0280;FT0;RT0;XT0;TQ0;"]
        with patch("socket.create_connection") as connect:
            connect.return_value.__enter__.return_value = cat
            state = operating_state()
        self.assertEqual(state["MD"], "6")
        self.assertEqual(state["DT"], "0")
        self.assertEqual(state["BW"], "0280")
        cat.sendall.assert_called_once_with(b"FA;MD;DT;BW;FT;RT;XT;TQ;")

    def test_data_a_selection_waits_past_reverse_and_wrong_submode(self):
        before = {"MD": "2", "DT": "0", "BW": "0280", "TQ": "0"}
        good = before | {"MD": "6"}
        states = iter([before, good | {"DT": "1"}, good | {"MD": "9"}])
        with (
            patch("qk4_cat.operating_state", side_effect=lambda: next(states, good)),
            patch("qk4_cat.rig") as rig,
            patch("qk4_cat.time.monotonic", side_effect=itertools.count(0, 0.1)),
            patch("qk4_cat.time.sleep"),
        ):
            self.assertEqual(select_data_a(), good)
        rig.assert_called_once_with("M", "PKTUSB", "2800")

    def test_mode_selection_never_runs_while_radio_is_transmitting(self):
        with (
            patch("qk4_cat.operating_state", return_value={"TQ": "1"}),
            patch("qk4_cat.rig") as rig,
            self.assertRaisesRegex(RuntimeError, "transmitting"),
        ):
            select_data_a()
        rig.assert_not_called()

    def test_filter_is_applied_after_data_submode_recalls_a_narrower_filter(self):
        before = {"MD": "2", "DT": "0", "BW": "0280", "TQ": "0"}
        recalled = before | {"MD": "6", "BW": "0250"}
        wanted = recalled | {"BW": "0280"}
        events = []
        cat = MagicMock()
        cat.sendall.side_effect = lambda frame: events.append(frame)
        with (
            patch("qk4_cat.operating_state", return_value=before),
            patch("qk4_cat.rig", side_effect=lambda *args: events.append(args)),
            patch("qk4_cat._wait_mode", side_effect=[recalled, wanted]),
            patch("socket.create_connection") as connect,
        ):
            connect.return_value.__enter__.return_value = cat
            self.assertEqual(select_data_a(), wanted)
        self.assertEqual(events, [("M", "PKTUSB", "2800"), b"BW0280;"])

    def test_native_restore_keeps_reverse_orientation_and_rtty_submode(self):
        cat = MagicMock()
        saved = {"MD": "9", "DT": "1", "BW": "0050"}
        with (
            patch("socket.create_connection") as connect,
            patch("qk4_cat.wait_for_receive"),
            patch("qk4_cat._wait_mode") as wait,
        ):
            connect.return_value.__enter__.return_value = cat
            restore_mode(saved)
        self.assertEqual(
            [call.args[0] for call in cat.sendall.call_args_list],
            [b"MD9;DT1;MD9;", b"BW0050;"],
        )
        wait.assert_called_with(saved)
