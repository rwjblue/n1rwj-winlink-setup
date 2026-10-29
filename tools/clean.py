"""Archive stopped-station diagnostics without removing mail or dependencies."""

import datetime
import fcntl
from pathlib import Path
import shutil
import socket

from station_config import ROOT, config


def clean():
    local = ROOT / ".local"
    local.mkdir(exist_ok=True, mode=0o700)
    with (local / "station.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Station running; use mise run stop before cleanup")
        if (local / "station.json").exists():
            raise SystemExit(
                "Station state exists; stop and verify the station before cleanup"
            )
        cfg = config()
        for port in (cfg["cat_guard_port"], cfg["rigctld_port"], cfg["http_port"]):
            with socket.socket() as probe:
                probe.settimeout(0.2)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    raise SystemExit(
                        f"Station port {port} is active; stop before cleanup"
                    )
        items = [p for p in local.iterdir() if p.name not in {"pat", "station.lock"}]
        items += [
            p for p in (ROOT / ".ruff_cache", ROOT / ".pytest_cache") if p.exists()
        ]
        if not items:
            print(
                "No diagnostic artifacts to archive; mailbox and dependencies preserved"
            )
            return
        base = Path.home() / "Library/Application Support/n1rwj-winlink-setup/archives"
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        base.chmod(0o700)
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%fZ")
        archive = base / stamp
        archive.mkdir(mode=0o700)
        moved = []
        for source in sorted(items):
            relative = source.relative_to(ROOT)
            destination = archive / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), destination)
            moved.append(str(relative))
        (archive / "README.txt").write_text(
            f"Diagnostic archive from {ROOT}\nUTC archive: {stamp}\n"
            "Paths below are relative to the station repository. Mailbox, forms,\n"
            "configuration, source caches and dependencies were preserved.\n\n"
            + "\n".join(moved)
            + "\n"
        )
        print(f"Archived {len(moved)} diagnostic entries to {archive}")
        print(
            "Preserved .local/pat (mail, forms, config and RMS cache), .cache and .venv"
        )


if __name__ == "__main__":
    clean()
