"""Queue rendered modem audio for disk without waiting on writes while keyed."""

import datetime
import json
import queue
import threading
import time

import numpy as np
from scipy.io import wavfile

from hfmodem.core import levels


def stamp():
    return {
        "mono_s": time.monotonic(),
        "utc": datetime.datetime.now(datetime.UTC).isoformat(timespec="microseconds"),
    }


class BurstCapture:
    def __init__(self, folder):
        self.folder = folder
        folder.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.dropped = 0
        self.errors = []
        self._queue = queue.Queue(maxsize=32)
        self._thread = threading.Thread(target=self._write, daemon=True)
        self._thread.start()

    def emit(self, event, **fields):
        self._put(({"event": event, **stamp(), **fields}, None))

    def source(self, burst, samples, peak, **fields):
        # Copy only: normalization and WAV/JSON work run in the writer thread.
        self._put(
            (
                {"event": "source", **stamp(), "burst": burst, "peak": peak, **fields},
                np.array(samples, copy=True),
            )
        )

    def _put(self, item):
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self.dropped += 1

    def _write(self):
        try:
            with (self.folder / "events.jsonl").open("w") as log:
                while (item := self._queue.get()) is not None:
                    row, samples = item
                    try:
                        if samples is not None:
                            name = f"source-{row['burst']:04d}.wav"
                            played = levels.at_drive(samples, row["peak"])
                            # AudioVaraIO copies its normalized signal into Float32
                            # playback channels. Preserve that exact left channel.
                            wavfile.write(
                                self.folder / name, 48000, played.astype("float32")
                            )
                            row.update(wav=name, frames=len(played), sample_rate=48000)
                        log.write(json.dumps(row) + "\n")
                        log.flush()
                    except Exception as error:
                        if len(self.errors) < 8:
                            self.errors.append(str(error))
        except OSError as error:
            self.errors.append(str(error))

    def close(self):
        if self._thread.is_alive():
            try:
                self._queue.put(None, timeout=2)
            except queue.Full:
                self.errors.append("Writer queue did not drain during shutdown")
            self._thread.join(timeout=5)
        result = {
            "scope": "Rendered playback source and host timing; not RF or QK4 output",
            "dropped_records": self.dropped,
            "errors": self.errors,
            "writer_stopped": not self._thread.is_alive(),
        }
        (self.folder / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
        return result
