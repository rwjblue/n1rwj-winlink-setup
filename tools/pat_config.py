"""Build Pat's disposable configuration from checked-in station settings."""

import datetime
import json
import os
from pathlib import Path
import shutil

from dotenv import dotenv_values

from build_pat import ensure_pat
from cli import ConfigError, run_cli
from station_config import ROOT, config


def configure(root=None):
    root = root or ROOT
    cfg = config(root)
    template = json.loads((root / "config/pat.json").read_text())
    if template.get("secure_login_password"):
        raise ConfigError(
            "Keep passwords out of config/pat.json; use WINLINK_PASSWORD in .env"
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
    return [
        str(ensure_pat()),
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


def credential_overrides():
    # Explicit path, no upward search or shell/variable interpolation. Password
    # characters such as $ and ${...} must reach Pat unchanged.
    values = dotenv_values(ROOT / ".env", interpolate=False)
    email = os.environ.get("WINLINK_EMAIL", values.get("WINLINK_EMAIL"))
    password = os.environ.get("WINLINK_PASSWORD", values.get("WINLINK_PASSWORD"))
    overrides = {}
    if email:
        login_call, separator, domain = email.strip().partition("@")
        station_call = config(ROOT)["callsign"].upper()
        if (
            not separator
            or domain.lower() != "winlink.org"
            or login_call.upper() != station_call
        ):
            raise ConfigError(
                "WINLINK_EMAIL must be CALLSIGN@winlink.org and match callsign in config/station.toml"
            )
        overrides["PAT_MYCALL"] = station_call
    if "PAT_SECURE_LOGIN_PASSWORD" not in os.environ and password is not None:
        overrides["PAT_SECURE_LOGIN_PASSWORD"] = password
    return overrides


def pat_environment():
    # Scope XDG to Pat's child process; its RMS caches and form counters also
    # belong here. Do not redirect other programs' settings or read home hooks.
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"WINLINK_EMAIL", "WINLINK_PASSWORD"}
        and (
            not key.startswith("PAT_")
            or key in {"PAT_SECURE_LOGIN_PASSWORD", "PAT_DEBUG"}
        )
    }
    env.update(credential_overrides())
    for kind in ("CONFIG", "DATA", "STATE"):
        env[f"XDG_{kind}_HOME"] = str(ROOT / ".local")
    env["XDG_CACHE_HOME"] = str(ROOT / ".cache")
    # Only our repository hook may run inside the station Pat process.
    env["PAT_STATION_QSY_HOOK"] = str(ROOT / "bin/pat-qsy")
    return env


def main():
    os.umask(0o077)
    target = configure()
    cfg = config()
    print(f"Station: {cfg['callsign']} / {cfg['locator']}")
    print(f"Settings: {ROOT / 'config/station.toml'} and {ROOT / 'config/pat.json'}")
    print(f"Generated Pat config: {target}")
    print(
        f"Winlink password available to Pat: {bool(pat_environment().get('PAT_SECURE_LOGIN_PASSWORD'))}"
    )
    print(
        "Credentials: project .env or explicit environment; never written into Pat JSON"
    )


if __name__ == "__main__":
    run_cli(main)
