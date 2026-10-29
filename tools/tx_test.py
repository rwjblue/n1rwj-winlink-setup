"""Prepare, or explicitly execute, one short identified transmit test.

Default is a pure dry run. Execution requires separate human approval in chat
and confirmation of the selected dummy load or operator-approved antenna.
This test replaces Pat as the sole PTT owner; never run it beside the station.
"""

import argparse
import json
import signal
import socket
import subprocess
import sys
import threading
import time

import numpy as np
import sounddevice as sd
from hfmodem.core import cwid
from hfmodem.core.busy import is_busy
from hfmodem.core.occupied import occupied_hz

from qk4_cat import native_power, wait_for_receive
from station import LOCAL
from station_config import ROOT, config


def emergency_unkey():
    wait_for_receive(request_rx=True)
    print("QK4 reports TQ0 (radio receive)", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-transmit", action="store_true")
    parser.add_argument("--dummy-load-confirmed", action="store_true")
    parser.add_argument("--antenna-confirmed", action="store_true")
    parser.add_argument("--dial-khz", type=float, default=14101.5)
    parser.add_argument("--amplifier-bypassed", action="store_true")
    parser.add_argument(
        "--unkey", action="store_true", help="Emergency RX only; never keys"
    )
    args = parser.parse_args()
    cfg = config()
    dial_hz = round(args.dial_khz * 1000)
    if not (7000000 <= dial_hz <= 7300000 or 14000000 <= dial_hz <= 14350000):
        parser.error("Test frequency must be on the approved 40m or 20m antenna bands")
    if args.unkey:
        emergency_unkey()
        return
    plan = {
        "dial_hz": dial_hz,
        "mode": "USB",
        "filter_hz": 2800,
        "power_limit_w": 5,
        "tone_hz": 1500,
        "signal": f"CW {cfg['callsign']} at 20 WPM",
        "signal_seconds": cwid.duration(cfg["callsign"], wpm=20),
        "audio_peak": min(cfg["amplitude"], 0.05),
        "tx_device": cfg["tx_device"],
        "maximum_key_seconds": 5,
        "restore": "frequency, mode, bandwidth and RF power after confirmed unkey",
        "requirements": "Explicit RF approval and confirmation of antenna or dummy load",
        "load": "operator-approved antenna" if args.antenna_confirmed else "dummy load",
    }
    print(json.dumps(plan, indent=2), flush=True)
    if not args.execute:
        print("DRY RUN: no devices or CAT connections opened")
        return
    if not (
        args.approved_transmit
        and (
            args.antenna_confirmed
            or (args.dummy_load_confirmed and args.amplifier_bypassed)
        )
    ):
        parser.error(
            "Execution requires RF approval and antenna confirmation, or dummy load plus amplifier bypass"
        )
    if (LOCAL / "station.json").exists():
        raise SystemExit(
            "Stop the normal station before the standalone transmit test"
        )
    for port in (cfg["cat_guard_port"], cfg["rigctld_port"], 8300, 8301):
        with socket.socket() as check:
            check.bind(("127.0.0.1", port))

    def rig(*command):
        return (
            subprocess.check_output(
                [
                    "rigctl",
                    "-m",
                    "2",
                    "-r",
                    f"127.0.0.1:{cfg['rigctld_port']}",
                    *command,
                ],
                text=True,
                timeout=8,
            )
            .strip()
            .splitlines()
        )

    processes = []
    logs = []
    snapshot = None
    saved_power = None
    telemetry = []
    telemetry_stop = threading.Event()
    monitor = None

    def observe_radio():
        try:
            with socket.create_connection(
                (cfg["qk4_host"], cfg["qk4_port"]), timeout=2
            ) as cat:
                cat.settimeout(0.3)
                while not telemetry_stop.is_set():
                    cat.sendall(b"TQ;TM;")
                    try:
                        reply = cat.recv(4096).decode("ascii", errors="replace")
                        telemetry.append({"mono_s": time.monotonic(), "reply": reply})
                    except TimeoutError:
                        pass
                    telemetry_stop.wait(0.1)
        except OSError as error:
            telemetry.append({"error": str(error)})

    def stop(*_):
        raise KeyboardInterrupt

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)
    try:
        (LOCAL / "logs").mkdir(parents=True, exist_ok=True)
        for name, command in [
            (
                "tx-guard",
                [
                    sys.executable,
                    "tools/cat_guard.py",
                    "--approved-transmit",
                    "--max-key-seconds",
                    "5",
                ],
            ),
            (
                "tx-rigctld",
                [
                    "rigctld",
                    "-m",
                    "2047",
                    "-r",
                    f"127.0.0.1:{cfg['cat_guard_port']}",
                    "-T",
                    "127.0.0.1",
                    "-t",
                    str(cfg["rigctld_port"]),
                    "-P",
                    "RIG",
                ],
            ),
        ]:
            log = (LOCAL / "logs" / (name + ".log")).open("a")
            logs.append(log)
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log)
            processes.append(process)
            time.sleep(0.5)
            if process.poll() is not None:
                raise RuntimeError(f"{name} failed; inspect its log")
        for attempt in range(10):
            try:
                original = rig("f", "m", "t")
                if len(original) == 4:
                    break
            except subprocess.SubprocessError, OSError:
                if attempt == 9:
                    raise
            time.sleep(0.2)
        else:
            raise RuntimeError("Cannot obtain complete radio snapshot")
        if original[-1] != "0":
            raise RuntimeError("Radio already transmitting; test refused")
        snapshot = original
        saved_power = native_power()
        (LOCAL / "tx-test-before.json").write_text(
            json.dumps({"radio": original, "power": saved_power.decode()})
        )
        rig("M", "USB", "2800", "F", str(dial_hz))
        power = native_power(b"PC050L")  # K4 QRP units are tenths of a watt.
        readback = rig("f", "m", "t")
        if (
            readback[:3] != [str(dial_hz), "USB", "2800"]
            or power != b"PC050L"
            or readback[-1] != "0"
        ):
            raise RuntimeError(f"Test settings did not read back correctly: {readback}")
        if args.antenna_confirmed:
            time.sleep(2)  # Discard old-frequency receiver/sink buffers.
            channel = sd.rec(
                5 * 48000,
                samplerate=48000,
                channels=1,
                dtype="float32",
                device=cfg["rx_device"],
            )
            sd.wait()
            busy, _, margin = is_busy(channel[:, 0], 48000, occupied_hz("vara", "2300"))
            print(
                f"Channel assessment: busy={busy}, margin={margin:.1f} dB", flush=True
            )
            if busy:
                raise RuntimeError("Channel occupied; antenna transmission refused")
        samples = cwid.audio(
            cfg["callsign"],
            wpm=20,
            tone_hz=1500,
            fs=48000,
            amplitude=plan["audio_peak"],
        )
        stereo = np.repeat(samples[:, None], 2, axis=1)
        # Open/prime output with silence before asserting PTT. Pat is absent;
        # this test process is the only PTT controller.
        with sd.OutputStream(
            device=cfg["tx_device"], samplerate=48000, channels=2, dtype="float32"
        ) as audio:
            audio.write(np.zeros((4800, 2), dtype="float32"))
            monitor = threading.Thread(target=observe_radio, daemon=True)
            monitor.start()
            rig("T", "1")
            time.sleep(cfg["ptt_lead_seconds"])
            audio.write(stereo)
            audio.write(
                np.zeros((int(48000 * cfg["tx_tail_seconds"]), 2), dtype="float32")
            )
        rig("T", "0")
        emergency_unkey()
        print(
            "Identification completed; inspect telemetry and verify RF power/ALC before declaring success"
        )
    finally:
        sd.stop()
        telemetry_stop.set()
        if monitor is not None:
            monitor.join(timeout=2)
            (LOCAL / "logs/tx-telemetry.json").write_text(
                json.dumps(telemetry, indent=2)
            )
            print(
                "Observed TQ1:",
                any("TQ1;" in row.get("reply", "") for row in telemetry),
                flush=True,
            )
        try:
            emergency_unkey()
            if snapshot:
                rig("M", snapshot[1], snapshot[2], "F", snapshot[0])
                if saved_power is not None and native_power(saved_power) != saved_power:
                    raise RuntimeError("Power restoration readback failed")
                print("Restored radio settings:", rig("f", "m", "t"))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            for log in logs:
                log.close()


if __name__ == "__main__":
    main()
