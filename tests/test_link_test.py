import contextlib
import io
import itertools
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import link_test


class LinkTestPlanning(unittest.TestCase):
    def test_brief_optimistic_frequency_match_is_not_a_settled_tune(self):
        good = {
            "FA": "00007100000",
            "MD": "6",
            "DT": "0",
            "BW": "0280",
            "FT": "0",
            "RT": "0",
            "XT": "0",
        }
        bad = dict(good, FA="00014108500")
        states = iter([good])
        with (
            patch("link_test.operating_state", side_effect=lambda: next(states, bad)),
            patch("link_test.time.monotonic", side_effect=itertools.count()),
            patch("link_test.time.sleep"),
            self.assertRaises(RuntimeError),
        ):
            link_test.require_frequency(7100000, settle_seconds=3, stable_seconds=1)

    def test_unconfirmed_qsy_never_starts_connect(self):
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder)
            (local / "logs").mkdir()
            (local / "station.json").write_text('{"transmit":true}')
            previous = {"FA": "00014108500", "TQ": "0"}
            with (
                patch(
                    "sys.argv",
                    [
                        "link_test",
                        "varahf:///KB8AY?bw=2750&freq=7100",
                        "--execute",
                        "--approved-transmit",
                    ],
                ),
                patch("link_test.LOCAL", local),
                patch("link_test.native_power", return_value=b"PC050H"),
                patch("link_test.operating_state", return_value=previous),
                patch("link_test.select_data_a"),
                patch("link_test.api", return_value={}) as api,
                patch(
                    "link_test.require_frequency",
                    side_effect=RuntimeError("wrong frequency"),
                ),
                patch("link_test.restore_frequency") as restore,
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaisesRegex(RuntimeError, "wrong frequency"),
            ):
                link_test.main()
            self.assertEqual(
                [call.args[0] for call in api.call_args_list], ["status", "qsy"]
            )
            restore.assert_called_once_with(14108500)

    def test_split_and_offsets_refuse_an_otherwise_correct_dial(self):
        for key in ("FT", "RT", "XT"):
            state = {
                "FA": "00007100000",
                "MD": "6",
                "DT": "0",
                "BW": "0280",
                "FT": "0",
                "RT": "0",
                "XT": "0",
            }
            state[key] = "1"
            with (
                self.subTest(key=key),
                patch("link_test.operating_state", return_value=state),
                self.assertRaises(RuntimeError),
            ):
                link_test.require_frequency(7100000)

    def test_plain_usb_reverse_data_rtty_and_narrow_filters_are_rejected(self):
        good = {
            "FA": "00007100000",
            "MD": "6",
            "DT": "0",
            "BW": "0280",
            "FT": "0",
            "RT": "0",
            "XT": "0",
        }
        for changes in ({"MD": "2"}, {"MD": "9"}, {"DT": "1"}, {"BW": "0050"}):
            with (
                self.subTest(changes=changes),
                patch("link_test.operating_state", return_value=good | changes),
                self.assertRaisesRegex(RuntimeError, "DATA-A normal"),
            ):
                link_test.require_frequency(7100000)
        with patch("link_test.operating_state", return_value=good):
            self.assertEqual(link_test.require_frequency(7100000), good)
        with patch("link_test.operating_state", return_value=good | {"BW": "0300"}):
            self.assertEqual(link_test.require_frequency(7100000)["BW"], "0300")

    def test_failed_cancel_requests_supervised_rf_shutdown(self):
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder)
            with (
                patch("link_test.LOCAL", local),
                patch("link_test.api", side_effect=TimeoutError),
                self.assertRaises(TimeoutError),
            ):
                link_test.cancel_attempt(MagicMock())
            self.assertTrue((local / "stop-request").exists())

    def test_acknowledged_cancel_with_live_dial_cannot_leave_rf_enabled(self):
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder)
            with (
                patch("link_test.LOCAL", local),
                patch(
                    "link_test.api", return_value={"dialing": False, "connected": False}
                ),
                self.assertRaisesRegex(RuntimeError, "still running"),
            ):
                link_test.cancel_attempt(MagicMock(is_alive=lambda: True))
            self.assertTrue((local / "stop-request").exists())

    def test_default_plan_never_contacts_the_station(self):
        with (
            patch("sys.argv", ["link_test", "varahf:///KB8AY?bw=2750&freq=7100"]),
            patch("link_test.api") as api,
            patch("link_test.native_power") as power,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            link_test.main()
        api.assert_not_called()
        power.assert_not_called()

    def test_unapproved_execution_never_contacts_the_station(self):
        with (
            patch(
                "sys.argv",
                ["link_test", "varahf:///KB8AY?bw=2750&freq=7100", "--execute"],
            ),
            patch("link_test.api") as api,
            patch("link_test.native_power") as power,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            link_test.main()
        api.assert_not_called()
        power.assert_not_called()
