import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from scipy.io import wavfile
from hfmodem.core import levels

from burst_capture import BurstCapture
from kestrel import AudioVaraIO, StationAudio


class RenderedCapture(unittest.TestCase):
    def test_saved_source_is_exact_float32_playback_with_metadata(self):
        source = np.array([0.0, 0.7, -1.4, 0.2])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "session"
            recorder = BurstCapture(root)
            recorder.source(7, source, 0.35, metadata={"packet_kind": "link-setup"})
            # A caller reusing its source must not mutate the queued recording.
            source[:] = 9
            result = recorder.close()
            rate, actual = wavfile.read(root / "source-0007.wav")
            events = [
                json.loads(line)
                for line in (root / "events.jsonl").read_text().splitlines()
            ]
        expected = levels.at_drive(np.array([0.0, 0.7, -1.4, 0.2]), 0.35).astype(
            "float32"
        )
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(rate, 48000)
        self.assertEqual(events[0]["metadata"]["packet_kind"], "link-setup")
        self.assertEqual(result["dropped_records"], 0)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["writer_stopped"])

    def test_disk_failure_is_reported_without_blocking_the_modem(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = BurstCapture(Path(folder) / "session")
            with patch("burst_capture.wavfile.write", side_effect=OSError("disk full")):
                recorder.source(1, np.ones(4), 0.35)
                result = recorder.close()
        self.assertIn("disk full", result["errors"])
        self.assertTrue(result["writer_stopped"])

    def test_receive_only_never_records_or_plays_an_outgoing_waveform(self):
        audio = StationAudio.__new__(StationAudio)
        audio.transmit = False
        audio.capture = Mock()
        with patch.object(AudioVaraIO, "tx") as play:
            with self.assertRaises(PermissionError):
                audio.tx(np.ones(4))
        audio.capture.source.assert_not_called()
        play.assert_not_called()

    def test_capture_tracks_the_same_drive_and_burst_as_playback(self):
        audio = StationAudio.__new__(StationAudio)
        audio.transmit = True
        audio.capture = Mock()
        audio._tx_event_seq = 4
        audio._tx_metadata = {"packet_kind": "link-setup"}
        audio.samples = 123
        audio.amp = 0.35
        audio.lead = 0
        with patch.object(AudioVaraIO, "tx") as play:
            audio.tx(np.ones(4), drive=0.2)
        self.assertEqual(audio.capture.source.call_args.args[0], 5)
        self.assertEqual(audio.capture.source.call_args.args[2], 0.2)
        self.assertEqual(play.call_args.kwargs, {"drive": 0.2})
        audio.capture.emit.assert_called_once_with(
            "playback_returned", burst=5, rx_sample=123
        )

    def test_diagnostics_flag_does_not_enable_transmission(self):
        import station

        with (
            patch("sys.argv", ["station", "start", "--receive-only", "--diagnostics"]),
            patch("station.run_stack") as run_stack,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            station.main()
        run_stack.assert_called_once_with(transmit=False, diagnostics=True)
