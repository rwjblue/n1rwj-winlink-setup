"""Passively record both Loopback inputs and read-only QK4 timing telemetry.

Never opens an audio output, attaches to a modem, tunes, or sends PTT commands.
Default invocation prints a plan without opening any devices or connections.
"""

import argparse
import contextlib
import datetime
import json
import math
import os
from pathlib import Path
import queue
import socket
import threading
import time
import wave

import numpy as np
import sounddevice as sd

from cli import UserError, run_cli
from station_config import ROOT, config

RATE = 48000
RADIO_QUERY = b"TQ;TM;"


class InputCapture:
    def __init__(self, folder, name):
        self.folder, self.name = folder, name
        self.captured = self.written = self.dropped = 0
        self.errors = []
        self.xruns = 0
        self.peak = np.zeros(2)
        self.square_sum = np.zeros(2)
        self.clipped = 0
        self._queue = queue.Queue(maxsize=256)
        self._thread = threading.Thread(target=self._write, daemon=True)
        self._thread.start()

    def callback(self, data, frames, timing, status):
        now = time.monotonic()
        row = {
            "capture_frame": self.captured,
            "frames": frames,
            "callback_mono_s": now,
            "portaudio_adc_s": timing.inputBufferAdcTime,
            "portaudio_current_s": timing.currentTime,
            "estimated_adc_mono_s": now
            + timing.inputBufferAdcTime
            - timing.currentTime,
            "status": str(status),
        }
        self.captured += frames
        if status:
            self.xruns += 1
        try:
            self._queue.put_nowait((row, data.copy()))
        except queue.Full:
            self.dropped += frames

    def _write(self):
        try:
            with (
                wave.open(str(self.folder / f"{self.name}.wav"), "wb") as wav,
                (self.folder / f"{self.name}-timing.jsonl").open("w") as log,
            ):
                wav.setnchannels(2)
                wav.setsampwidth(4)
                wav.setframerate(RATE)
                while (item := self._queue.get()) is not None:
                    row, data = item
                    if not np.isfinite(data).all():
                        raise ValueError("Audio contains non-finite samples")
                    row["file_frame"] = self.written
                    pcm = np.rint(np.clip(data, -1, 1).astype(float) * (2**31 - 1))
                    wav.writeframes(pcm.astype("<i4").tobytes())
                    log.write(json.dumps(row) + "\n")
                    self.written += len(data)
                    self.peak = np.maximum(self.peak, np.max(np.abs(data), axis=0))
                    self.square_sum += np.sum(data.astype(float) ** 2, axis=0)
                    self.clipped += int(np.count_nonzero(np.abs(data) >= 0.999))
        except Exception as error:
            self.errors.append(str(error))

    def close(self):
        if self._thread.is_alive():
            try:
                self._queue.put(None, timeout=2)
            except queue.Full:
                self.errors.append("Capture writer did not drain")
            self._thread.join(timeout=5)
        return {
            "captured_frames": self.captured,
            "written_frames": self.written,
            "dropped_frames": self.dropped,
            "stream_status_count": self.xruns,
            "peak_dbfs": (20 * np.log10(np.maximum(self.peak, 1e-12))).tolist(),
            "rms_dbfs": (
                10 * np.log10(np.maximum(self.square_sum / max(1, self.written), 1e-24))
            ).tolist(),
            "clipped_samples": self.clipped,
            "errors": self.errors,
            "writer_stopped": not self._thread.is_alive(),
        }


def poll_radio(cfg, folder, stop, result):
    """Only these two GETs are sent. Opening CAT never grants this tool PTT."""
    result.update(polls=0, incomplete_polls=0, errors=[], tq_values=[])
    try:
        with (
            socket.create_connection(
                (cfg["qk4_host"], cfg["qk4_port"]), timeout=2
            ) as cat,
            (folder / "radio.jsonl").open("w") as log,
        ):
            cat.settimeout(0.2)
            pending = b""
            while not stop.is_set():
                row = {
                    "request_mono_s": time.monotonic(),
                    "query": RADIO_QUERY.decode(),
                    "replies": [],
                }
                cat.sendall(RADIO_QUERY)
                deadline = time.monotonic() + 0.5
                seen = set()
                while time.monotonic() < deadline and seen != {"TQ", "TM"}:
                    try:
                        part = cat.recv(4096)
                    except TimeoutError:
                        continue
                    if not part:
                        raise OSError("QK4 closed its read-only telemetry connection")
                    pending += part
                    if len(pending) > 16384:
                        raise OSError("Oversized QK4 telemetry reply")
                    while b";" in pending:
                        frame, pending = pending.split(b";", 1)
                        text = frame.decode("ascii", errors="replace")
                        if text in ("TQ0", "TQ1") or (
                            text.startswith("TM") and text[2:].isdigit()
                        ):
                            row["replies"].append(
                                {"mono_s": time.monotonic(), "frame": text}
                            )
                            seen.add(text[:2])
                            if (
                                text.startswith("TQ")
                                and text not in result["tq_values"]
                            ):
                                result["tq_values"].append(text)
                row["complete"] = seen == {"TQ", "TM"}
                log.write(json.dumps(row) + "\n")
                log.flush()
                result["polls"] += 1
                result["incomplete_polls"] += int(not row["complete"])
                stop.wait(max(0, 0.1 - (time.monotonic() - row["request_mono_s"])))
    except OSError as error:
        result["errors"].append(str(error))


def capture(seconds, folder, cfg):
    folder.mkdir(parents=True, mode=0o700, exist_ok=False)
    manifest = {
        "started_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "started_mono_s": time.monotonic(),
        "sample_rate": RATE,
        "channels": 2,
        "wav_format": "signed PCM32; left and right channels preserved",
        "devices": {
            direction: cfg[direction + "_device"] for direction in ("rx", "tx")
        },
        "requested_seconds": seconds,
        "radio_queries": RADIO_QUERY.decode(),
        "timing_limits": "ADC times are callback-anchored estimates. TQ/TM are polled QK4 state, not measured RF/PTT edges. Use per-block file_frame mapping; never assume two input streams share an origin or have no gaps.",
    }
    state = ROOT / ".local/station.json"
    manifest["station_at_start"] = (
        json.loads(state.read_text()) if state.exists() else None
    )
    log_offsets = {}
    for name in ("kestrel", "cat-guard", "pat"):
        path = ROOT / ".local/logs" / f"{name}.log"
        if path.exists():
            log_offsets[path] = path.stat().st_size
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    writers = {}
    stop = threading.Event()
    radio = {}
    observer = None
    completed_duration = False
    try:
        with contextlib.ExitStack() as stack:
            for direction in ("rx", "tx"):
                writer = InputCapture(folder, direction)
                writers[direction] = writer
                stack.enter_context(
                    sd.InputStream(
                        device=cfg[direction + "_device"],
                        samplerate=RATE,
                        channels=2,
                        dtype="float32",
                        callback=writer.callback,
                    )
                )
            observer = threading.Thread(
                target=poll_radio, args=(cfg, folder, stop, radio), daemon=True
            )
            observer.start()
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if radio.get("errors") or any(
                    writer.errors for writer in writers.values()
                ):
                    raise UserError(
                        "Capture failed; inspect manifest.json and partial recordings"
                    )
                stop.wait(min(0.1, max(0, deadline - time.monotonic())))
            completed_duration = True
    finally:
        stop.set()
        if observer is not None:
            observer.join(timeout=2)
        manifest["audio"] = {name: writer.close() for name, writer in writers.items()}
        manifest["warnings"] = []
        rx = manifest["audio"].get("rx", {})
        if rx.get("written_frames") and max(rx["peak_dbfs"]) <= -120:
            manifest["warnings"].append(
                "RX cable was silent; capture integrity does not verify receive routing. "
                "Check QK4 connection and speaker device with mise run doctor."
            )
        manifest["radio"] = radio
        manifest["radio_observer_stopped"] = observer is None or not observer.is_alive()
        manifest["finished_mono_s"] = time.monotonic()
        for path, offset in log_offsets.items():
            with path.open("rb") as log:
                log.seek(offset)
                (folder / path.name).write_bytes(log.read())
        manifest["complete"] = (
            completed_duration
            and len(writers) == 2
            and all(
                r["written_frames"]
                and not r["errors"]
                and not r["dropped_frames"]
                and not r["stream_status_count"]
                and r["writer_stopped"]
                for r in manifest["audio"].values()
            )
            and radio.get("polls", 0) > 0
            and not radio.get("errors")
            and not radio.get("incomplete_polls", 0)
            and manifest["radio_observer_stopped"]
        )
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if not manifest["complete"]:
        raise UserError(
            f"Capture has gaps or incomplete telemetry: {folder / 'manifest.json'}"
        )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Open audio INPUTS and read-only CAT telemetry",
    )
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or not 0 < args.seconds <= 600:
        parser.error("--seconds must be above zero and at most 600")
    cfg = config()
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    folder = (
        args.output or ROOT / ".local/recordings" / f"handshake-{stamp}"
    ).resolve()
    if not args.execute:
        print(
            json.dumps(
                {
                    "output": str(folder),
                    "seconds": args.seconds,
                    "audio_inputs": [cfg["rx_device"], cfg["tx_device"]],
                    "radio_queries": RADIO_QUERY.decode(),
                    "playback": False,
                    "ptt": False,
                },
                indent=2,
            )
        )
        print(
            "PLAN ONLY: no devices or connections opened. Add --execute for passive capture."
        )
        return
    os.umask(0o077)
    if folder.exists():
        raise UserError(f"Output folder already exists: {folder}")
    try:
        result = capture(args.seconds, folder, cfg)
    except (OSError, sd.PortAudioError) as error:
        raise UserError(f"Passive capture failed: {error}. Inspect {folder}") from error
    print(
        json.dumps(
            {
                "output": str(folder),
                "audio": result["audio"],
                "radio": result["radio"],
                "warnings": result["warnings"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    run_cli(main)
