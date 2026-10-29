"""Verify DATA-A receive audio and Pat QSY without enabling transmission."""

import argparse
import json
import urllib.request

from cli import UserError, run_cli
from audio import capture
from link_test import require_frequency
from qk4_cat import operating_state, restore_frequency, restore_mode, select_data_a
from station_config import ROOT, config
from modems import MODEMS, active_modem


def qsy(khz):
    request = urllib.request.Request(
        f"http://127.0.0.1:{config()['http_port']}/api/qsy",
        data=json.dumps(
            {"transport": MODEMS[active_modem()]["transport"], "freq": khz}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dial-khz",
        type=float,
        help="Optional test dial; default is the current frequency",
    )
    args = parser.parse_args()
    station = ROOT / ".local/station.json"
    if not station.exists():
        raise SystemExit(
            "Station stopped: connect QK4, then mise run start --receive-only"
        )
    running = json.loads(station.read_text())
    if running["transmit"]:
        raise SystemExit(
            "Use mise run stop, then mise run start --receive-only for this check"
        )
    before = operating_state()
    if before["TQ"] != "0":
        raise SystemExit("Radio is transmitting; receive check refused")
    (ROOT / ".local/radio-before-receive-test.json").write_text(
        json.dumps(before, indent=2)
    )
    hz = round(args.dial_khz * 1000) if args.dial_khz is not None else int(before["FA"])
    try:
        qsy(hz / 1000)
        select_data_a()
        require_frequency(hz, settle_seconds=5, stable_seconds=1)
        print(f"Pat QSY verified: {hz} Hz DATA-A normal, RX >=2800 Hz, PTT off")
        result = capture(10, config()["rx_device"], ROOT / ".local/receive-data-a.wav")
        if result["rms_dbfs"][0] <= -100 or result["clipped_samples"]:
            raise UserError("Main receive audio is silent or clipped")
    finally:
        restore_frequency(int(before["FA"]))
        restore_mode(before)
        restored = operating_state()
        print("Restored:", restored)
        if restored != before:
            raise UserError("Radio restoration readback failed")


if __name__ == "__main__":
    run_cli(main)
