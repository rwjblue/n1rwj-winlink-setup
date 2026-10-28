"""Prepare, or explicitly execute, one short dummy-load tone test.

Default is a pure dry run. Execution requires separate human approval in chat
and confirmation that the dummy load and amplifier bypass are in place.
This test replaces Pat as the sole PTT owner; never run it beside the station.
"""

import argparse
import json
import signal
import socket
import subprocess
import sys
import time

import numpy as np
import sounddevice as sd

from station import LOCAL
from station_config import ROOT, config


def emergency_unkey():
    cfg = config()
    with socket.create_connection((cfg["qk4_host"], cfg["qk4_port"]), timeout=2) as cat:
        cat.sendall(b"RX;TQ;")
        cat.settimeout(2)
        response = b""
        while b"TQ0;" not in response:
            part = cat.recv(4096)
            if not part:
                raise RuntimeError("QK4 disconnected before unkey readback")
            response += part
    print("QK4 reports TQ0 (radio receive)", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-transmit", action="store_true")
    parser.add_argument("--dummy-load-confirmed", action="store_true")
    parser.add_argument("--amplifier-bypassed", action="store_true")
    parser.add_argument(
        "--unkey", action="store_true", help="Emergency RX only; never keys"
    )
    args = parser.parse_args()
    cfg = config()
    if args.unkey:
        emergency_unkey()
        return
    plan = {
        "dial_hz": 14101500,
        "mode": "USB",
        "filter_hz": 2800,
        "power_limit_w": 5,
        "tone_hz": 1500,
        "tone_seconds": 1,
        "audio_peak": min(cfg["amplitude"], 0.05),
        "tx_device": cfg["tx_device"],
        "maximum_key_seconds": 5,
        "restore": "frequency, mode, bandwidth and RF power after confirmed unkey",
        "requirements": "Explicit RF approval, 50-ohm dummy load, external amplifier bypassed",
    }
    print(json.dumps(plan, indent=2), flush=True)
    if not args.execute:
        print("DRY RUN: no devices or CAT connections opened")
        return
    if not all(
        (args.approved_transmit, args.dummy_load_confirmed, args.amplifier_bypassed)
    ):
        parser.error(
            "Execution requires RF approval, dummy load confirmation and amplifier bypass"
        )
    if (LOCAL / "station.json").exists():
        raise SystemExit(
            "Stop the normal station before the standalone dummy-load test"
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
                original = rig("f", "m", "l", "RFPOWER", "t")
                if len(original) == 5:
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
        (LOCAL / "tx-test-before.json").write_text(json.dumps(original))
        rig("M", "USB", "2800", "F", "14101500", "L", "RFPOWER", ".05")
        readback = rig("f", "m", "l", "RFPOWER", "t")
        if (
            readback[:3] != ["14101500", "USB", "2800"]
            or float(readback[3]) > 0.051
            or readback[-1] != "0"
        ):
            raise RuntimeError(f"Test settings did not read back correctly: {readback}")
        samples = (0.05 * np.sin(2 * np.pi * 1500 * np.arange(48000) / 48000)).astype(
            "float32"
        )
        samples *= plan["audio_peak"] / 0.05
        stereo = np.repeat(samples[:, None], 2, axis=1)
        # Open/prime output with silence before asserting PTT. Pat is absent;
        # this test process is the only PTT controller.
        with sd.OutputStream(
            device=cfg["tx_device"], samplerate=48000, channels=2, dtype="float32"
        ) as audio:
            audio.write(np.zeros((4800, 2), dtype="float32"))
            rig("T", "1")
            time.sleep(cfg["ptt_lead_seconds"])
            audio.write(stereo)
            audio.write(
                np.zeros((int(48000 * cfg["tx_tail_seconds"]), 2), dtype="float32")
            )
        rig("T", "0")
        emergency_unkey()
        print(
            "Tone completed; verify RF wattmeter, ALC and dummy-load heating before declaring success"
        )
    finally:
        sd.stop()
        try:
            emergency_unkey()
            if snapshot:
                rig(
                    "M",
                    snapshot[1],
                    snapshot[2],
                    "F",
                    snapshot[0],
                    "L",
                    "RFPOWER",
                    snapshot[3],
                )
                print("Restored radio settings:", rig("f", "m", "l", "RFPOWER", "t"))
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
