"""Prepare, or explicitly execute, one short identified transmit test.

Default is a pure dry run. RF execution requires human approval and load
confirmation. The off-air variant requires positive K4 TX TEST readback in
QK4 Vail, with the radio's RF output inhibited.
This test replaces Pat as the sole PTT owner; never run it beside the station.
"""

import argparse
import json
import re
import signal
import socket
import subprocess
import sys
import threading
import time

import numpy as np
import sounddevice as sd
from hfmodem.core import cwid, levels
from hfmodem.core.busy import is_busy
from hfmodem.core.occupied import occupied_hz

from cli import UserError, run_cli
from qk4_cat import (
    native_power,
    operating_state,
    restore_mode,
    select_data_a,
    wait_for_receive,
)
from station import LOCAL
from station_config import ROOT, config
from qk4_test_mode import require_radio_test_mode


def test_waveform(callsign, kind, peak):
    if kind == "vara-connect":
        from hfmodem.kestrel.vara import vara_frames, vara_mfsk

        samples = vara_mfsk.synth_burst("N0CALL", vara_frames.connect_request("2300"))
    else:
        samples = cwid.audio(callsign, wpm=20, tone_hz=1500, fs=48000)
    # Match AudioVaraIO.tx(): normalize each rendered burst to its configured peak.
    return levels.at_drive(samples, peak)


def emergency_unkey():
    wait_for_receive(request_rx=True)
    print("QK4 reports TQ0 (radio receive)", flush=True)


def verify_off_air_telemetry(rows):
    replies = "".join(row.get("reply", "") for row in rows)
    meters = re.findall(r"TM\d{3}\d{3}(\d{3})\d{3};", replies)
    if "TQ1;" not in replies or not meters:
        raise UserError("Off-air check lacks logical TX or forward-power telemetry")
    if any(int(value) for value in meters):
        raise UserError("Nonzero forward power during K4 TX TEST; inspect telemetry")
    return {
        "logical_tx_observed": True,
        "forward_meter_samples": len(meters),
        "forward_power_zero": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-transmit", action="store_true")
    parser.add_argument("--dummy-load-confirmed", action="store_true")
    parser.add_argument("--antenna-confirmed", action="store_true")
    parser.add_argument(
        "--radio-test-mode",
        action="store_true",
        help="Off-air: requires the K4 TX TEST indicator, verified through QK4 Vail",
    )
    parser.add_argument("--dial-khz", type=float, default=14101.5)
    parser.add_argument("--signal", choices=("cw", "vara-connect"), default="cw")
    parser.add_argument(
        "--audio-peak",
        type=float,
        help="Temporary peak drive for TX TEST calibration (0 < peak <= 1)",
    )
    parser.add_argument("--amplifier-bypassed", action="store_true")
    parser.add_argument(
        "--unkey", action="store_true", help="Emergency RX only; never keys"
    )
    args = parser.parse_args()
    if args.signal != "cw" and not args.radio_test_mode:
        parser.error("The VARA calibration waveform requires --radio-test-mode")
    if args.audio_peak is not None and (
        not args.radio_test_mode or not 0 < args.audio_peak <= 1
    ):
        parser.error(
            "--audio-peak requires --radio-test-mode and a value above 0 up to 1"
        )
    cfg = config()
    dial_hz = round(args.dial_khz * 1000)
    if not (7000000 <= dial_hz <= 7300000 or 14000000 <= dial_hz <= 14350000):
        parser.error("Test frequency must be on the approved 40m or 20m antenna bands")
    if args.unkey:
        emergency_unkey()
        return
    peak = cfg["amplitude"] if args.audio_peak is None else args.audio_peak
    samples = test_waveform(cfg["callsign"], args.signal, peak)
    plan = {
        "dial_hz": dial_hz,
        "mode": "DATA-A normal (Hamlib PKTUSB; MD6/DT0)",
        "minimum_rx_filter_hz": 2800,
        "power": "radio's current setting (unchanged)",
        "tone_hz": 1500,
        "signal": f"CW {cfg['callsign']} at 20 WPM"
        if args.signal == "cw"
        else "Kestrel BW2300 connect request to N0CALL (off-air)",
        "signal_seconds": len(samples) / 48000,
        "audio_peak": peak,
        "tx_device": cfg["tx_device"],
        "maximum_key_seconds": 5,
        "restore": "frequency, mode and bandwidth after confirmed unkey",
        "requirements": "Verified K4 TX TEST, or explicit RF approval and load confirmation",
        "load": "K4 TX TEST (RF inhibited)"
        if args.radio_test_mode
        else "operator-approved antenna"
        if args.antenna_confirmed
        else "dummy load",
    }
    print(json.dumps(plan, indent=2), flush=True)
    if not args.execute:
        print("DRY RUN: no devices or CAT connections opened")
        return
    if args.radio_test_mode:
        require_radio_test_mode()
    elif not (
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
        raise SystemExit("Stop the normal station before the standalone transmit test")
    for port in (cfg["cat_guard_port"], cfg["rigctld_port"], 8300, 8301):
        with socket.socket() as check:
            check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
    native_snapshot = None
    telemetry = []
    telemetry_stop = threading.Event()
    monitor = None
    completed = False

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
                raise UserError(f"{name} failed; inspect its log")
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
            raise UserError("Cannot obtain complete radio snapshot")
        if original[-1] != "0":
            raise UserError("Radio already transmitting; test refused")
        snapshot = original
        native_snapshot = operating_state()
        (LOCAL / "tx-test-before.json").write_text(
            json.dumps({"radio": native_snapshot, "power": native_power().decode()})
        )
        rig("F", str(dial_hz))
        select_data_a()
        print(
            f"RF power readback: {native_power().decode()} (radio controlled)",
            flush=True,
        )
        readback = rig("f", "m", "t")
        if (
            readback[:2] != [str(dial_hz), "PKTUSB"]
            or int(readback[2]) < 2800
            or readback[-1] != "0"
        ):
            raise UserError(f"Test settings did not read back correctly: {readback}")
        if args.antenna_confirmed and not args.radio_test_mode:
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
                raise UserError("Channel occupied; antenna transmission refused")
        stereo = np.repeat(samples[:, None], 2, axis=1)
        # Open/prime output with silence before asserting PTT. Pat is absent;
        # this test process is the only PTT controller.
        with sd.OutputStream(
            device=cfg["tx_device"], samplerate=48000, channels=2, dtype="float32"
        ) as audio:
            audio.write(np.zeros((4800, 2), dtype="float32"))
            monitor = threading.Thread(target=observe_radio, daemon=True)
            monitor.start()
            if args.radio_test_mode:
                require_radio_test_mode()  # Recheck after tuning, immediately before PTT.
            rig("T", "1")
            time.sleep(cfg["ptt_lead_seconds"])
            audio.write(stereo)
            audio.write(
                np.zeros((int(48000 * cfg["tx_tail_seconds"]), 2), dtype="float32")
            )
        rig("T", "0")
        emergency_unkey()
        completed = True
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
                rig("F", snapshot[0])
                if native_snapshot:
                    restore_mode(native_snapshot)
                print("Restored radio settings:", rig("f", "m", "t"))
            if args.radio_test_mode and completed:
                require_radio_test_mode()
                print(
                    "Off-air DATA-A result:",
                    json.dumps(verify_off_air_telemetry(telemetry)),
                )
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
    run_cli(main)
