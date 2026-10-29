"""Read-only station checks; never attaches to Kestrel's command socket."""

import json
import subprocess
import urllib.request

import sounddevice as sd

from qk4_cat import DATA_A_BANDWIDTH, is_data_a, operating_state
from station import LOCAL
from station_config import config


def main():
    cfg = config()
    state = LOCAL / "station.json"
    if not state.exists():
        raise SystemExit("Station stopped: connect QK4, then mise run start")
    status = json.loads(state.read_text())
    for direction in ("rx", "tx"):
        name = cfg[direction + "_device"]
        getattr(
            sd, "check_input_settings" if direction == "rx" else "check_output_settings"
        )(
            device=name,
            samplerate=48000,
            channels=1 if direction == "rx" else 2,
            dtype="float32",
        )
    with urllib.request.urlopen(
        f"http://127.0.0.1:{cfg['http_port']}/api/status", timeout=3
    ) as response:
        api = json.load(response)
    radio = (
        subprocess.check_output(
            [
                "rigctl",
                "-m",
                "2",
                "-r",
                f"127.0.0.1:{cfg['rigctld_port']}",
                "f",
                "m",
                "t",
            ],
            text=True,
            timeout=8,
        )
        .strip()
        .splitlines()
    )
    native = operating_state()
    result = {
        "transmit_enabled": status["transmit"],
        "active_listeners": api["active_listeners"],
        "radio": radio,
        "native_mode": {key: native[key] for key in ("MD", "DT", "BW", "TQ")},
        "audio_devices": [cfg["rx_device"], cfg["tx_device"]],
    }
    print(json.dumps(result, indent=2))
    if radio[-1] != "0":
        raise SystemExit("Radio reports transmit; use mise run unkey if unexpected")
    if not is_data_a(native) or int(native["BW"]) * 10 < DATA_A_BANDWIDTH:
        raise SystemExit(
            "Expected DATA-A normal, RX >=2800 Hz; restart the station to select it"
        )
    if "varahf" not in api["active_listeners"]:
        raise SystemExit("Pat VARA listener not ready; inspect .local/logs")


if __name__ == "__main__":
    main()
