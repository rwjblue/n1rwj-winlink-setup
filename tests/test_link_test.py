import contextlib
import io
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import link_test


class LinkTestPlanning(unittest.TestCase):
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

    def test_default_plan_never_contacts_the_station(self):
        with (
            patch("sys.argv", ["link_test", "varahf:///KB8AY?bw=2750&freq=7100"]),
            patch("link_test.api") as api,
            patch("link_test.require_five_watt_limit") as power,
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
            patch("link_test.require_five_watt_limit") as power,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            link_test.main()
        api.assert_not_called()
        power.assert_not_called()
