"""Back up and configure QK4 preferences while the app is closed."""

import argparse
import datetime
import json
import pathlib
import plistlib
import shutil
import subprocess

from station_config import ROOT, config

DOMAIN = "com.qk4.QK4"


def audio_device_settings(devices=None):
    cfg = config()
    if devices is None:
        probe = ROOT / ".cache/bin/qt-audio-probe"
        if not probe.exists():
            raise RuntimeError("Missing Qt audio probe; run mise run setup")
        devices = json.loads(subprocess.check_output([str(probe)], text=True))
    settings = {}
    for key, name, is_input in (
        ("audio.speakerDevice", cfg["rx_device"], False),
        ("audio.micDevice", cfg["tx_device"], True),
    ):
        matches = [
            d
            for d in devices
            if d["name"] == name
            and d["input"] == is_input
            and d["qk4_format_supported"]
        ]
        if len(matches) != 1:
            raise RuntimeError(f"No unique compatible Qt audio device: {name}")
        settings[key] = matches[0]["id"]
    return settings


def verify_audio_devices(preferences=None, devices=None):
    """Check saved audio selections and calibration gain; never expose credentials."""
    expected = audio_device_settings(devices)
    if preferences is None:
        prefs = pathlib.Path.home() / "Library/Preferences" / (DOMAIN + ".plist")
        preferences = plistlib.loads(prefs.read_bytes()) if prefs.exists() else {}
    wrong = [key for key, value in expected.items() if preferences.get(key) != value]
    if preferences.get("audio.micGain") != config()["qk4_mic_gain"]:
        wrong.append("audio.micGain")
    if wrong:
        raise RuntimeError(
            f"QK4 saved audio settings differ at {', '.join(wrong)}. "
            "Quit QK4, run mise run configure-qk4, then reopen QK4 Vail and connect."
        )
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", type=int, default=1, help="QK4 saved radio index, starting at 1"
    )
    parser.add_argument(
        "--restore", type=pathlib.Path, help="Restore a previous preference backup"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview settings without changing preferences",
    )
    args = parser.parse_args()
    if (
        subprocess.run(["pgrep", "-x", "QK4"], stdout=subprocess.DEVNULL).returncode
        == 0
        and not args.dry_run
    ):
        raise SystemExit("Quit QK4 before changing its preferences")
    prefs = pathlib.Path.home() / "Library/Preferences" / (DOMAIN + ".plist")
    backup = (
        pathlib.Path.home()
        / "Library/Application Support/n1rwj-winlink-setup/backups"
        / (datetime.datetime.now(datetime.UTC).strftime("qk4-%Y%m%dT%H%M%S%fZ.plist"))
    )
    if not args.dry_run:
        backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        backup.parent.chmod(0o700)
    if prefs.exists() and not args.dry_run:
        shutil.copy2(prefs, backup)
        backup.chmod(0o600)
        print(f"Backup: {backup}")
    if args.restore:
        if args.dry_run:
            print(f"Would restore QK4 preferences from {args.restore.resolve()}")
            return
        subprocess.run(
            ["defaults", "import", DOMAIN, str(args.restore.resolve())], check=True
        )
        return
    cfg = config()
    settings = {
        key: ("-string", value) for key, value in audio_device_settings().items()
    }
    settings.update(
        {
            "audio.monoMixEnabled": ("-bool", "false"),
            "audio.subVolume": ("-int", "0"),
            "audio.volume": ("-int", str(cfg["qk4_rx_volume"])),
            "audio.micGain": ("-int", str(cfg["qk4_mic_gain"])),
            "audio.rxBoostDb": ("-int", "0"),
            "kpa1500.enabled": ("-bool", "false"),
            "catServer.enabled": ("-bool", "true"),
            "catServer.port": ("-int", str(cfg["qk4_port"])),
            f"radios.{args.profile}.encodeMode": ("-int", "0"),
            f"radios.{args.profile}.streamingLatency": ("-int", "0"),
        }
    )
    if args.dry_run:
        print(
            json.dumps({key: value for key, (_, value) in settings.items()}, indent=2)
        )
        print(
            "DRY RUN: no preferences changed; existing radio connection and credentials preserved"
        )
        return
    for key, (kind, value) in settings.items():
        subprocess.run(["defaults", "write", DOMAIN, key, kind, value], check=True)
    print(
        "Configured raw EM0/SL0, Loopback, audio gains, RX boost off, amplifier integration off and CAT. Relaunch QK4 and connect."
    )


if __name__ == "__main__":
    main()
