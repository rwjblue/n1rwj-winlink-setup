"""Back up and configure QK4 preferences while the app is closed."""

import argparse
import datetime
import json
import pathlib
import shutil
import subprocess

from station_config import ROOT, config

DOMAIN = "com.qk4.QK4"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", type=int, default=1, help="QK4 saved radio index, starting at 1"
    )
    parser.add_argument(
        "--restore", type=pathlib.Path, help="Restore a previous preference backup"
    )
    args = parser.parse_args()
    if (
        subprocess.run(["pgrep", "-x", "QK4"], stdout=subprocess.DEVNULL).returncode
        == 0
    ):
        raise SystemExit("Quit QK4 before changing its preferences")
    prefs = pathlib.Path.home() / "Library/Preferences" / (DOMAIN + ".plist")
    backup = (
        pathlib.Path.home()
        / "Library/Application Support/n1rwj-winlink-setup/backups"
        / (datetime.datetime.now(datetime.UTC).strftime("qk4-%Y%m%dT%H%M%S%fZ.plist"))
    )
    backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup.parent.chmod(0o700)
    if prefs.exists():
        shutil.copy2(prefs, backup)
        backup.chmod(0o600)
        print(f"Backup: {backup}")
    if args.restore:
        subprocess.run(
            ["defaults", "import", DOMAIN, str(args.restore.resolve())], check=True
        )
        return
    cfg = config()
    devices = json.loads(
        subprocess.check_output([str(ROOT / ".cache/bin/qt-audio-probe")], text=True)
    )
    settings = {}
    for key, name, is_input in [
        ("speakerDevice", cfg["rx_device"], False),
        ("micDevice", cfg["tx_device"], True),
    ]:
        matches = [
            d
            for d in devices
            if d["name"] == name
            and d["input"] == is_input
            and d["qk4_format_supported"]
        ]
        if len(matches) != 1:
            raise SystemExit(f"No unique compatible Qt audio device: {name}")
        settings["audio." + key] = ("-string", matches[0]["id"])
    settings.update(
        {
            "audio.monoMixEnabled": ("-bool", "false"),
            "audio.subVolume": ("-int", "0"),
            "catServer.enabled": ("-bool", "true"),
            "catServer.port": ("-int", str(cfg["qk4_port"])),
            f"radios.{args.profile}.encodeMode": ("-int", "0"),
            f"radios.{args.profile}.streamingLatency": ("-int", "0"),
        }
    )
    for key, (kind, value) in settings.items():
        subprocess.run(["defaults", "write", DOMAIN, key, kind, value], check=True)
    print(
        "Configured raw EM0, SL0, main RX left, Loopback RX/TX and CAT. Relaunch QK4 and connect."
    )


if __name__ == "__main__":
    main()
