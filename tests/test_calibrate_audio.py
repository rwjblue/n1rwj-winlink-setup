import contextlib
import io
import unittest
from unittest.mock import patch

import calibrate_audio


class DriveCalibration(unittest.TestCase):
    def test_default_plan_opens_no_audio_radio_or_ui(self):
        with (
            patch("sys.argv", ["calibrate_audio"]),
            patch("calibrate_audio.require_radio_test_mode") as test_mode,
            patch("calibrate_audio.operating_state") as state,
            patch("calibrate_audio.subprocess.run") as run,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            calibrate_audio.main()
        test_mode.assert_not_called()
        state.assert_not_called()
        run.assert_not_called()

    def test_alc_response_is_reported_only_with_logical_tx_and_zero_forward_power(self):
        rows = [{"reply": "TQ1;TM000000000010;TM004000000010;TQ0;"}]
        self.assertEqual(calibrate_audio.summarize(rows)["peak_alc"], 4)
        with self.assertRaises(RuntimeError):
            calibrate_audio.summarize([{"reply": "TQ1;TM004000010010;"}])
