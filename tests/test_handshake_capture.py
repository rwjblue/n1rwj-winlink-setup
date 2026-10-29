import contextlib
import io
import json
from pathlib import Path
import queue
import socket
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import wave

import numpy as np

import handshake_capture as capture


class PassiveCapture(unittest.TestCase):
    def test_plan_opens_no_audio_or_network_and_creates_no_files(self):
        with (
            patch("sys.argv", ["capture-handshake"]),
            patch.object(
                capture.sd, "InputStream", side_effect=AssertionError("audio")
            ),
            patch.object(
                capture.socket, "create_connection", side_effect=AssertionError("CAT")
            ),
            patch.object(Path, "mkdir", side_effect=AssertionError("mkdir")),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            capture.main()
        self.assertIn("PLAN ONLY", output.getvalue())

    def test_captures_two_inputs_and_only_sends_status_queries(self):
        received = []
        inputs = []
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen()
        server.settimeout(2)

        def respond():
            with server, server.accept()[0] as client:
                while data := client.recv(4096):
                    received.append(data)
                    client.sendall(b"TQ0;TM000000000000;")

        radio = threading.Thread(target=respond)
        radio.start()

        class Input:
            def __init__(self, **kwargs):
                inputs.append(kwargs)
                self.callback = kwargs["callback"]
                self.clock = len(inputs) * 1000

            def __enter__(self):
                self.callback(
                    np.array([[0.25, -0.5], [0.125, -0.25]], dtype="float32"),
                    2,
                    types.SimpleNamespace(
                        currentTime=self.clock, inputBufferAdcTime=self.clock - 0.02
                    ),
                    capture.sd.CallbackFlags(),
                )
                return self

            def __exit__(self, *_args):
                pass

        cfg = {
            "rx_device": "test RX",
            "tx_device": "test TX",
            "qk4_host": "127.0.0.1",
            "qk4_port": server.getsockname()[1],
        }
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                out = root / "session"
                with (
                    patch.object(capture, "ROOT", root),
                    patch.object(capture.sd, "InputStream", Input),
                    patch.object(
                        capture.sd, "OutputStream", side_effect=AssertionError("output")
                    ),
                    patch.object(
                        capture.sd, "play", side_effect=AssertionError("playback")
                    ),
                ):
                    result = capture.capture(0.05, out, cfg)
                self.assertTrue(result["complete"])
                self.assertEqual(result["radio"]["tq_values"], ["TQ0"])
                self.assertEqual([i["device"] for i in inputs], ["test RX", "test TX"])
                for direction in ("rx", "tx"):
                    with wave.open(str(out / f"{direction}.wav"), "rb") as wav:
                        self.assertEqual(
                            (
                                wav.getnchannels(),
                                wav.getframerate(),
                                wav.getsampwidth(),
                            ),
                            (2, 48000, 4),
                        )
                        pcm = np.frombuffer(wav.readframes(2), "<i4").reshape(-1, 2)
                        np.testing.assert_allclose(
                            pcm / (2**31 - 1), [[0.25, -0.5], [0.125, -0.25]]
                        )
                    row = json.loads((out / f"{direction}-timing.jsonl").read_text())
                    self.assertAlmostEqual(
                        row["callback_mono_s"] - row["estimated_adc_mono_s"], 0.02
                    )
        finally:
            radio.join(timeout=3)
        self.assertFalse(radio.is_alive())
        self.assertEqual(b"".join(received), capture.RADIO_QUERY * len(received))

    def test_dropped_buffers_keep_the_file_to_capture_mapping_explicit(self):
        timing = types.SimpleNamespace(inputBufferAdcTime=1, currentTime=1.01)
        with tempfile.TemporaryDirectory() as folder:
            writer = capture.InputCapture(Path(folder), "tx")
            with patch.object(writer._queue, "put_nowait", side_effect=queue.Full):
                writer.callback(np.zeros((3, 2)), 3, timing, capture.sd.CallbackFlags())
            writer.callback(
                np.ones((2, 2)) * 0.1, 2, timing, capture.sd.CallbackFlags()
            )
            result = writer.close()
            row = json.loads((Path(folder) / "tx-timing.jsonl").read_text())
        self.assertEqual(result["dropped_frames"], 3)
        self.assertEqual((row["capture_frame"], row["file_frame"]), (3, 0))
        self.assertEqual((result["captured_frames"], result["written_frames"]), (5, 2))

    def test_second_device_failure_closes_writer_and_marks_partial_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (
                patch.object(capture, "ROOT", root),
                patch.object(
                    capture.sd,
                    "InputStream",
                    side_effect=[contextlib.nullcontext(), OSError("missing cable")],
                ),
                self.assertRaisesRegex(OSError, "missing cable"),
            ):
                capture.capture(
                    0.01, root / "partial", {"rx_device": "rx", "tx_device": "tx"}
                )
            result = json.loads((root / "partial/manifest.json").read_text())
        self.assertFalse(result["complete"])
        self.assertTrue(result["audio"]["rx"]["writer_stopped"])
        self.assertTrue(result["audio"]["tx"]["writer_stopped"])

    def test_silent_rx_is_reported_even_when_capture_integrity_is_good(self):
        @contextlib.contextmanager
        def silent_input(**kwargs):
            kwargs["callback"](
                np.zeros((16, 2), dtype="float32"),
                16,
                types.SimpleNamespace(currentTime=1, inputBufferAdcTime=1),
                capture.sd.CallbackFlags(),
            )
            yield

        def radio(_cfg, _folder, _stop, result):
            result.update(polls=1, errors=[], incomplete_polls=0, tq_values=["TQ0"])

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (
                patch.object(capture, "ROOT", root),
                patch.object(capture.sd, "InputStream", silent_input),
                patch.object(capture, "poll_radio", radio),
            ):
                result = capture.capture(
                    0.01, root / "silent", {"rx_device": "rx", "tx_device": "tx"}
                )
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("RX cable was silent", result["warnings"][0])
