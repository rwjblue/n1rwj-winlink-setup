import contextlib
import io
import unittest
from unittest.mock import patch

import tx_test


class TransmitPreparation(unittest.TestCase):
    def test_cw_and_real_modem_waveforms_use_the_same_peak_normalization(self):
        import numpy as np

        for signal in ("cw", "vara-connect", "ardop-connect"):
            with self.subTest(signal=signal):
                samples = tx_test.test_waveform("N1RWJ", signal, 0.4)
                self.assertGreater(len(samples), 48000)
                self.assertTrue(np.isfinite(samples).all())
                self.assertAlmostEqual(float(np.max(np.abs(samples))), 0.4, places=6)

    def test_ardop_waveform_matches_live_modem_before_playback(self):
        import numpy as np
        from ardop import StationAudio, StationModem
        from unittest.mock import Mock

        modem = StationModem(transmit=True, bandwidth=2000)
        audio = StationAudio(
            modem, tx_test.config() | {"ptt_lead_seconds": 0, "tx_tail_seconds": 0}
        )
        audio.transmit_enabled = True
        modem.set_mycall("N1RWJ")
        modem.start(Mock())
        try:
            with patch("ardop.play_drained") as playback:
                modem.connect("N0CALL", 1)
            live = playback.call_args.args[0][:, 0]
            expected = tx_test.test_waveform(
                "N1RWJ", "ardop-connect", tx_test.config()["amplitude"]
            )
            np.testing.assert_array_equal(live, expected)
        finally:
            modem.stop()

    def test_ardop_plan_is_offline_and_execution_requires_positive_test_mode(self):
        for flags in ([], ["--execute"]):
            with (
                self.subTest(flags=flags),
                patch(
                    "sys.argv",
                    [
                        "tx_test",
                        "--signal",
                        "ardop-connect",
                        "--radio-test-mode",
                        *flags,
                    ],
                ),
                patch(
                    "tx_test.require_radio_test_mode",
                    side_effect=RuntimeError("no TX TEST"),
                ),
                patch("socket.create_connection") as connect,
                patch("sounddevice.OutputStream") as stream,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                if flags:
                    with self.assertRaisesRegex(RuntimeError, "no TX TEST"):
                        tx_test.main()
                else:
                    tx_test.main()
            connect.assert_not_called()
            stream.assert_not_called()

    def test_default_plan_uses_station_drive_without_the_old_five_percent_cap(self):
        cfg = tx_test.config() | {"amplitude": 0.8}
        with (
            patch("sys.argv", ["tx_test"]),
            patch("tx_test.config", return_value=cfg),
            patch("socket.create_connection") as connect,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            tx_test.main()
        self.assertIn('"audio_peak": 0.8', output.getvalue())
        connect.assert_not_called()

    def test_calibration_override_requires_test_mode_and_valid_peak_before_io(self):
        for args in (
            ["--audio-peak", "0.8"],
            ["--radio-test-mode", "--audio-peak", "0"],
            ["--radio-test-mode", "--audio-peak", "1.1"],
            ["--radio-test-mode", "--audio-peak", "nan"],
        ):
            with (
                self.subTest(args=args),
                patch("sys.argv", ["tx_test", "--execute", *args]),
                patch("socket.create_connection") as connect,
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                tx_test.main()
            connect.assert_not_called()

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

    def test_off_air_result_requires_logical_tx_and_zero_forward_meter_readback(self):
        result = tx_test.verify_off_air_telemetry(
            [{"reply": "TQ1;TM000000000010;TQ0;"}]
        )
        self.assertTrue(result["forward_power_zero"])
        for reply in ("TQ0;TM000000000010;", "TQ1;", "TQ1;TM000000050010;"):
            with self.subTest(reply=reply), self.assertRaises(RuntimeError):
                tx_test.verify_off_air_telemetry([{"reply": reply}])

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

    def test_unconfirmed_hardware_test_mode_never_opens_radio_or_audio(self):
        with (
            patch("sys.argv", ["tx_test", "--execute", "--radio-test-mode"]),
            patch(
                "tx_test.require_radio_test_mode",
                side_effect=RuntimeError("no TX TEST"),
            ),
            patch("socket.create_connection") as connect,
            patch("sounddevice.OutputStream") as stream,
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "no TX TEST"),
        ):
            tx_test.main()
        connect.assert_not_called()
        stream.assert_not_called()
