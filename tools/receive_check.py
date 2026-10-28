"""Temporarily tune via Pat, record receive audio, then restore frequency/mode."""

import json
import subprocess
import urllib.request

from audio import capture
from station_config import ROOT, config


def rig(*args):
    return (
        subprocess.check_output(
            ["rigctl", "-m", "2", "-r", f"127.0.0.1:{config()['rigctld_port']}", *args],
            text=True,
            timeout=8,
        )
        .strip()
        .splitlines()
    )


def qsy(khz):
    request = urllib.request.Request(
        f"http://127.0.0.1:{config()['http_port']}/api/qsy",
        data=json.dumps({"transport": "varahf", "freq": khz}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def main():
    frequency, mode, bandwidth, ptt = rig("f", "m", "t")
    if ptt != "0":
        raise SystemExit("Radio is transmitting; receive check refused")
    snapshot = {"frequency_hz": frequency, "mode": mode, "bandwidth_hz": bandwidth}
    (ROOT / ".local/radio-before-receive-test.json").write_text(
        json.dumps(snapshot, indent=2)
    )
    try:
        rig("M", "USB", "2800")
        qsy(14101.5)
        readback = rig("f", "m", "t")
        if readback != ["14101500", "USB", "2800", "0"]:
            raise RuntimeError(f"Unexpected readback: {readback}")
        print("Pat QSY verified: 14.1015 MHz USB, 2800 Hz, PTT off")
        capture(10, config()["rx_device"], ROOT / ".local/receive-raw.wav")
    finally:
        rig("M", mode, bandwidth)
        qsy(int(frequency) / 1000)
        restored = rig("f", "m", "t")
        print("Restored:", restored)
        if restored != [frequency, mode, bandwidth, "0"]:
            raise RuntimeError("Radio restoration readback failed")


if __name__ == "__main__":
    main()
