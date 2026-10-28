import unittest
from unittest.mock import patch

from qk4_cat import require_five_watt_limit


class PowerLimit(unittest.TestCase):
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
