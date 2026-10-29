"""Inspect/capture Loopback audio and measure a cable with the TX gate CLOSED."""

import argparse
import json
import math
import threading
import time
import wave

import numpy as np
import sounddevice as sd
from scipy import signal

from qk4_cat import wait_for_receive
from station_config import ROOT, config


def stats(samples, rate):
    samples = np.asarray(samples)
    rms = np.sqrt(np.mean(samples.astype(float) ** 2, axis=0))
    peak = np.max(np.abs(samples), axis=0)
    return {
        "sample_rate": rate,
        "frames": len(samples),
        "rms_dbfs": np.round(20 * np.log10(np.maximum(rms, 1e-12)), 2).tolist(),
        "peak_dbfs": np.round(20 * np.log10(np.maximum(peak, 1e-12)), 2).tolist(),
        "clipped_samples": int(np.count_nonzero(np.abs(samples) >= 0.999)),
    }


def capture(seconds, name, output):
    rate = 48000
    # Devices are resolved by exact name; PortAudio must not silently choose
    # the Mac microphone or another system default if a cable disappears.
    data = sd.rec(
        int(seconds * rate), samplerate=rate, channels=2, device=name, dtype="float32"
    )
    sd.wait()
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes((np.clip(data, -1, 1) * 32767).astype("<i2").tobytes())
    result = {"device": name, **stats(data, rate)}
    print(json.dumps(result, indent=2))
    return result


def cable(name, rate):
    if not name.startswith(("K4 RX ", "WSJT-X TX ")):
        raise SystemExit("Cable tests require the named station Loopback devices")
    # RX cable tests require QK4 stopped: two writers would mix and invalidate
    # fidelity measurements. TX cable tests first force the QK4 gate closed.
    if name == config()["tx_device"]:
        state = ROOT / ".local/station.json"
        if state.exists() and json.loads(state.read_text())["transmit"]:
            raise SystemExit("Stop the RF station before injecting cable test audio")
        wait_for_receive(request_rx=True)
    source_rate = rate
    capture_rate = 48000
    t = np.arange(source_rate) / source_rate
    source = (0.03 * signal.chirp(t, 300, 1, 2700) * np.hanning(len(t))).astype(
        "float32"
    )
    captured, adc = [], []
    dac = []
    errors = []
    completed = threading.Event()
    cursor = 0
    capture_cursor = 0

    def receive(data, frames, timing, status):
        nonlocal capture_cursor
        if status:
            errors.append(str(status))
        adc.append(
            (
                capture_cursor,
                timing.inputBufferAdcTime,
                timing.currentTime,
                time.monotonic(),
            )
        )
        capture_cursor += frames
        captured.append(data[:, 0].copy())

    def send(data, frames, timing, status):
        nonlocal cursor
        if status:
            errors.append(str(status))
        if not dac:
            dac.append(
                (timing.outputBufferDacTime, timing.currentTime, time.monotonic())
            )
        data.fill(0)
        count = min(frames, len(source) - cursor)
        if count > 0:
            data[:count, :] = source[cursor : cursor + count, None]
        cursor += count
        if cursor >= len(source):
            raise sd.CallbackStop

    with sd.InputStream(
        device=name,
        samplerate=capture_rate,
        channels=2,
        dtype="float32",
        callback=receive,
    ):
        time.sleep(0.2)
        with sd.OutputStream(
            device=name,
            samplerate=source_rate,
            channels=2,
            dtype="float32",
            callback=send,
            finished_callback=completed.set,
        ):
            if not completed.wait(5):
                raise TimeoutError("Audio cable playback stalled")
        time.sleep(0.3)
    if name == config()["tx_device"]:
        wait_for_receive()
    actual = np.concatenate(captured)
    divisor = math.gcd(capture_rate, source_rate)
    expected = signal.resample_poly(
        source, capture_rate // divisor, source_rate // divisor
    )
    corr = signal.correlate(actual, expected, mode="valid", method="fft")
    offset = int(np.argmax(np.abs(corr)))
    window = actual[offset : offset + len(expected)]
    gain = float(np.dot(window, expected) / np.dot(expected, expected))
    residual = window - gain * expected
    snr = float(
        10
        * np.log10(np.mean((gain * expected) ** 2) / max(np.mean(residual**2), 1e-20))
    )
    # PortAudio streams can use different clock origins. Relate each stream's
    # currentTime to the same monotonic clock before comparing ADC and DAC.
    # The first output open can stall input on macOS. Use the block at the
    # detected onset instead of treating any lost earlier samples as present.
    anchor = max(
        (block for block in adc if block[0] <= offset), key=lambda block: block[0]
    )
    input_origin = anchor[3] - anchor[2]
    output_origin = dac[0][2] - dac[0][1]
    latency_ms = 1000 * (
        anchor[1]
        + (offset - anchor[0]) / capture_rate
        + input_origin
        - dac[0][0]
        - output_origin
    )
    result = {
        "device": name,
        "output_rate": source_rate,
        "capture_rate": capture_rate,
        "gain": round(gain, 6),
        "residual_snr_db": round(snr, 2),
        "callback_anchored_latency_ms": round(latency_ms, 2)
        if latency_ms >= 0
        else None,
        "latency_note": "Estimate only; callback scheduling and virtual-device timestamps require independent calibration",
        "stream_errors": errors,
    }
    print(json.dumps(result, indent=2))
    if abs(gain) < 0.01 or errors or snr < 25:
        raise SystemExit("Cable fidelity check failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["devices", "record", "cable"])
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--output", type=lambda s: ROOT / s)
    parser.add_argument("--direction", choices=["rx", "tx"], default="rx")
    args = parser.parse_args()
    if args.command == "devices":
        print(sd.query_devices())
    elif args.command == "record":
        capture(args.seconds, config()[args.direction + "_device"], args.output)
    else:
        cable(
            config()[args.direction + "_device"],
            12000 if args.direction == "rx" else 48000,
        )


if __name__ == "__main__":
    main()
