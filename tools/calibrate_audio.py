"""Measure audio drive in confirmed K4 TX TEST; default is a plan without IO."""

import argparse
import datetime
import json
import pathlib
import plistlib
import re
import shutil
import subprocess
import sys

from cli import UserError, log_error, run_cli
from qk4_cat import native_power, operating_state
from qk4_settings import DOMAIN, verify_audio_devices
from qk4_test_mode import require_radio_test_mode
from station_config import ROOT, config
from tx_test import verify_off_air_telemetry


def summarize(rows):
    result = verify_off_air_telemetry(rows)
    meters = re.findall(
        r"TM(\d{3})(\d{3})\d{6};", "".join(r.get("reply", "") for r in rows)
    )
    return result | {
        "peak_alc": max(int(alc) for alc, _ in meters),
        "peak_compression_db": max(int(cmp) for _, cmp in meters),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--dial-khz", type=float, help="Default: current radio dial")
    parser.add_argument(
        "--signal", choices=("cw", "vara-connect"), default="vara-connect"
    )
    parser.add_argument(
        "--peaks",
        nargs="+",
        type=float,
        default=[0.05, 0.1, 0.2, 0.3, 0.35, 0.4, 0.6, 0.8, 1.0],
    )
    args = parser.parse_args()
    if any(not 0 < p <= 1 for p in args.peaks) or args.peaks != sorted(set(args.peaks)):
        parser.error("Peaks must be unique, ascending, and above 0 up to 1")
    cfg = config()
    print(
        json.dumps(
            {
                "peaks": args.peaks,
                "qk4_mic_gain": cfg["qk4_mic_gain"],
                "signal": args.signal,
                "dial_khz": args.dial_khz,
                "target": "ALC 4, below the K4 5 mark",
                "rf": "inhibited by verified K4 TX TEST",
                "writes_defaults": False,
            },
            indent=2,
        ),
        flush=True,
    )
    if not args.execute:
        print("DRY RUN: no audio, CAT or UI access")
        return
    if (ROOT / ".local/station.json").exists():
        raise SystemExit("Stop the station before calibration")
    require_radio_test_mode()
    verify_audio_devices()
    prefs = plistlib.loads(
        (pathlib.Path.home() / "Library/Preferences" / (DOMAIN + ".plist")).read_bytes()
    )
    if prefs.get("audio.micGain") != cfg["qk4_mic_gain"]:
        raise SystemExit(
            "QK4 saved mic gain differs from station.toml; configure/relaunch QK4 first"
        )
    before = operating_state()
    if before["TQ"] != "0":
        raise SystemExit("Radio transmitting; calibration refused")
    power = native_power()
    khz = args.dial_khz if args.dial_khz is not None else int(before["FA"]) / 1000
    folder = (
        ROOT
        / ".local/logs"
        / datetime.datetime.now(datetime.UTC).strftime(
            "audio-calibration-%Y%m%dT%H%M%S%fZ"
        )
    )
    folder.mkdir(parents=True, mode=0o700)
    results = []
    report = {
        "radio_before": before,
        "power": power.decode(),
        "qk4_mic_gain": cfg["qk4_mic_gain"],
        "signal": args.signal,
        "results": results,
    }
    for index, peak in enumerate(args.peaks):
        case = folder / f"{index + 1:02d}-peak-{peak:g}"
        case.mkdir(mode=0o700)
        command = [
            sys.executable,
            "tools/tx_test.py",
            "--execute",
            "--radio-test-mode",
            "--dial-khz",
            str(khz),
            "--audio-peak",
            str(peak),
            "--signal",
            args.signal,
        ]
        with (case / "test.log").open("w") as log:
            run = subprocess.run(
                command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT
            )
        if run.returncode:
            raise log_error(
                f"Calibration case failed ({run.returncode}).", case / "test.log"
            )
        for source in ("logs/tx-telemetry.json", "tx-test-before.json"):
            shutil.copy2(ROOT / ".local" / source, case / pathlib.Path(source).name)
        result = {"audio_peak": peak} | summarize(
            json.loads((case / "tx-telemetry.json").read_text())
        )
        results.append(result)
        if native_power() != power:
            raise UserError("Radio power changed during calibration")
        (folder / "result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(result), flush=True)
        if result["peak_alc"] >= 4:
            break
    print(f"Calibration evidence: {folder}", flush=True)
    if not any(2 <= r["peak_alc"] <= 4 for r in results):
        raise SystemExit(
            "No suitable ALC response measured; do not select defaults from this run"
        )


if __name__ == "__main__":
    run_cli(main)
