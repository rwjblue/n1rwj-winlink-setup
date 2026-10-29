import unittest
from unittest.mock import patch

from qk4_test_mode import require_radio_test_mode


class RadioTestMode(unittest.TestCase):
    def test_only_positive_indicator_confirmation_allows_off_air_keying(self):
        with patch("qk4_test_mode.subprocess.check_output", return_value="true\n"):
            require_radio_test_mode()
        for result in ("false\n", "", "TEST", "SideControlPanel"):
            with (
                self.subTest(result=result),
                patch("qk4_test_mode.subprocess.check_output", return_value=result),
                self.assertRaises(RuntimeError),
            ):
                require_radio_test_mode()
