"""Build Pat's disposable configuration from checked-in station settings."""

import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess

from station_config import ROOT, config


def configure(root=None):
    root = root or ROOT
    cfg = config(root)
    template = json.loads((root / "config/pat.json").read_text())
    if template.get("secure_login_password"):
        raise ValueError(
            "Keep passwords out of config/pat.json; use PAT_SECURE_LOGIN_PASSWORD"
        )
    template.update(
        mycall=cfg["callsign"],
        locator=cfg["locator"],
        http_addr=f"127.0.0.1:{cfg['http_port']}",
        hamlib_rigs={
            "qk4": {
                "network": "tcp",
                "address": f"127.0.0.1:{cfg['rigctld_port']}",
                "VFO": "",
            }
        },
    )
    target = root / ".local/pat/config.json"
    for folder in ("pat/mailbox", "pat/forms", "pat/prehooks", "logs"):
        (root / ".local" / folder).mkdir(parents=True, exist_ok=True, mode=0o700)
    (root / ".local").chmod(0o700)
    content = json.dumps(template, indent=2) + "\n"
    if not target.exists() or target.read_text() != content:
        if target.exists():
            # Preserve edits made before this launcher became authoritative.
            backup = (
                Path.home() / "Library/Application Support/n1rwj-winlink-setup/backups"
            )
            backup.mkdir(parents=True, exist_ok=True, mode=0o700)
            backup.chmod(0o700)
            stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%fZ")
            saved = backup / f"pat-config-{stamp}.json"
            shutil.copy2(target, saved)
            saved.chmod(0o600)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(content)
        temporary.chmod(0o600)
        temporary.replace(target)
    target.chmod(0o600)
    return target


def pat_args(log_name="pat-cli"):
    try:
        # `which pat` on PATH now finds our launcher; mise resolves the pinned
        # upstream binary directly, so starting the supervisor cannot recurse.
        binary = subprocess.check_output(
            ["mise", "which", "pat"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit("Pat is not installed; run mise run setup") from error
    return [
        binary,
        "--config",
        str(configure()),
        "--mbox",
        str(ROOT / ".local/pat/mailbox"),
        "--forms",
        str(ROOT / ".local/pat/forms"),
        "--prehooks",
        str(ROOT / ".local/pat/prehooks"),
        "--event-log",
        str(ROOT / f".local/logs/{log_name}-events.json"),
        "--log",
        str(ROOT / f".local/logs/{log_name}.log"),
    ]


def pat_environment():
    # Scope XDG to Pat's child process; its RMS caches and form counters also
    # belong here. Do not redirect other programs' settings or read home hooks.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PAT_")
        or key in {"PAT_SECURE_LOGIN_PASSWORD", "PAT_DEBUG"}
    }
    for kind in ("CONFIG", "DATA", "STATE"):
        env[f"XDG_{kind}_HOME"] = str(ROOT / ".local")
    env["XDG_CACHE_HOME"] = str(ROOT / ".cache")
    return env


if __name__ == "__main__":
    os.umask(0o077)
    target = configure()
    cfg = config()
    print(f"Station: {cfg['callsign']} / {cfg['locator']}")
    print(f"Settings: {ROOT / 'config/station.toml'} and {ROOT / 'config/pat.json'}")
    print(f"Generated Pat config: {target}")
    print("Password: supplied only through PAT_SECURE_LOGIN_PASSWORD")
