"""Supervise the station as one unit, with optional receive-only operation."""

import argparse
import datetime
import fcntl
import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import time

from cli import UserError, log_error, run_cli
from station_config import ROOT, config
from qk4_cat import native_power, operating_state, select_data_a
from pat_config import configure, pat_args, pat_environment
from qk4_settings import verify_audio_devices
from modems import MODEMS, validate_pat_configuration

LOCAL = ROOT / ".local"
RESOURCE_LOCK = (
    pathlib.Path.home() / "Library/Application Support/n1rwj-winlink-setup/station.lock"
)


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.15):
            return True
    except OSError:
        return False


def run_stack(transmit=False, modem="vara", diagnostics=False):
    if diagnostics and modem != "vara":
        raise UserError(
            "--diagnostics records Kestrel only; use capture-handshake for passive ARDOP capture"
        )
    cfg = config()
    selected = MODEMS[modem]
    modem_process = selected["process"]
    LOCAL.mkdir(exist_ok=True, mode=0o700)
    (LOCAL / "logs").mkdir(exist_ok=True)
    RESOURCE_LOCK.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # The radio/audio path is shared across JJ workspaces, even when their
    # .local directories and configured control ports differ.
    with (
        RESOURCE_LOCK.open("a") as resource,
        (LOCAL / "station.lock").open("a") as lock,
    ):
        for handle in (resource, lock):
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SystemExit(
                    "Station already running (possibly in another workspace)"
                )
        for port in (
            cfg["cat_guard_port"],
            cfg["rigctld_port"],
            8300,
            8301,
            8515,
            8516,
            cfg["http_port"],
        ):
            if port_open(port):
                raise SystemExit(
                    f"Port {port} is in use; refusing to start a second stack"
                )
        # Admission precedes configuration, audio checks and any radio access.
        # In particular, never QSY an already running stack while switching.
        pat_env = pat_environment()
        verify_audio_devices()
        if transmit:
            print(
                f"RF power readback: {native_power().decode()} (radio controlled)",
                flush=True,
            )
        pat_config = json.loads(configure(modem=modem).read_text())
        validate_pat_configuration(pat_config, cfg, modem)
        with socket.create_connection((cfg["qk4_host"], cfg["qk4_port"]), timeout=2):
            pass
        stop = LOCAL / "stop-request"
        stop.unlink(missing_ok=True)
        state = LOCAL / "station.json"
        children = []
        child_logs = {}
        handles = []
        stopping = False

        def request_stop(*_):
            nonlocal stopping
            stopping = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, request_stop)

        def spawn(name, args, port, marker=None, env=None):
            path = LOCAL / "logs" / f"{name}.log"
            offset = path.stat().st_size if path.exists() else 0
            log = path.open("a")
            handles.append(log)
            process = subprocess.Popen(
                args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env
            )
            children.append((name, process))
            child_logs[name] = (path, offset)
            for _ in range(300):
                for child_name, child in children:
                    if child.poll() is not None:
                        raise log_error(
                            f"{child_name} exited ({child.returncode}) during startup.",
                            *child_logs[child_name],
                        )
                if stopping or stop.exists():
                    raise UserError("Startup cancelled")
                ready = (
                    marker
                    in path.read_bytes()[offset:].decode("utf-8", errors="replace")
                    if marker
                    else port_open(port)
                )
                if ready:
                    time.sleep(0.2)
                    print(f"{name} ready", flush=True)
                    return
                time.sleep(0.1)
            raise log_error(
                f"{name} did not become ready on port {port} within 30 seconds.",
                path,
                offset,
            )

        try:
            flags = ["--approved-transmit"] if transmit else []
            spawn(
                "cat-guard",
                [sys.executable, "tools/cat_guard.py", *flags],
                cfg["cat_guard_port"],
                "CAT guard ready",
            )
            spawn(
                "rigctld",
                [
                    "rigctld",
                    "-m",
                    "2047",
                    "-C",
                    "cache_timeout=0",
                    "-r",
                    f"127.0.0.1:{cfg['cat_guard_port']}",
                    "-T",
                    "127.0.0.1",
                    "-t",
                    str(cfg["rigctld_port"]),
                    "-P",
                    "RIG",
                ],
                cfg["rigctld_port"],
            )
            before = operating_state()
            snapshot = (
                LOCAL
                / "logs"
                / datetime.datetime.now(datetime.UTC).strftime(
                    "radio-before-data-a-%Y%m%dT%H%M%S%fZ.json"
                )
            )
            snapshot.write_text(json.dumps(before, indent=2))
            radio_selected = select_data_a()
            print(
                f"QK4 DATA-A normal, RX {int(radio_selected['BW']) * 10} Hz; previous state: {snapshot}",
                flush=True,
            )
            spawn(
                modem_process,
                [
                    sys.executable,
                    f"tools/{modem_process}.py",
                    *flags,
                    *(["--diagnostics"] if diagnostics else []),
                ],
                selected["port"],
                selected["ready"],
            )
            spawn(
                "pat",
                [
                    *pat_args(log_name="pat", modem=modem),
                    "http",
                    "--addr",
                    f"127.0.0.1:{cfg['http_port']}",
                ],
                cfg["http_port"],
                env=pat_env,
            )
            state.write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "transmit": transmit,
                        "diagnostics": diagnostics,
                        "modem": modem,
                        "children": {n: p.pid for n, p in children},
                    },
                    indent=2,
                )
            )
            print(
                f"Station ready; modem={modem}; transmit={transmit}; http://127.0.0.1:{cfg['http_port']}",
                flush=True,
            )
            while not stopping and not stop.exists():
                for name, process in children:
                    if process.poll() is not None:
                        raise log_error(
                            f"{name} exited ({process.returncode}); shutting down the station.",
                            *child_logs[name],
                        )
                time.sleep(0.1)
        finally:
            # Close the guarded CAT connection first: explicit RX and owner
            # disconnect unkey even if Pat or the audio process is stuck.
            for name in ("cat-guard", "pat", modem_process, "rigctld"):
                for child_name, process in children:
                    if child_name == name and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
            for handle in handles:
                handle.close()
            state.unlink(missing_ok=True)
            stop.unlink(missing_ok=True)
            print("Station stopped", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "stop", "status"])
    parser.add_argument("--background", action="store_true")
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Record Kestrel playback sources and detailed host timing",
    )
    parser.add_argument(
        "--modem",
        choices=MODEMS,
        default="vara",
        help="Station modem (default: vara); stop before switching",
    )
    parser.add_argument(
        "--receive-only",
        action="store_true",
        help="Block RF connections, keying and transmit audio",
    )
    args, extra = parser.parse_known_args()
    if extra:
        parser.error(f"Unexpected arguments: {extra}")
    if args.command == "start" and args.diagnostics and args.modem != "vara":
        parser.error(
            "--diagnostics records Kestrel only; use capture-handshake for passive ARDOP capture"
        )
    os.umask(0o077)
    if args.command == "status":
        state = LOCAL / "station.json"
        print(state.read_text() if state.exists() else "Station stopped")
    elif args.command == "stop":
        LOCAL.mkdir(exist_ok=True)
        (LOCAL / "stop-request").touch()
        for _ in range(100):
            if not (LOCAL / "station.json").exists():
                print("Station stopped")
                return
            time.sleep(0.1)
        raise log_error(
            "Shutdown did not complete within 10 seconds.",
            LOCAL / "logs/supervisor.log",
        )
    elif args.background:
        (LOCAL / "logs").mkdir(parents=True, exist_ok=True)
        flags = ["--receive-only"] if args.receive_only else []
        if args.diagnostics:
            flags.append("--diagnostics")
        if args.modem != "vara":
            flags += ["--modem", args.modem]
        with (LOCAL / "logs/supervisor.log").open("a") as log:
            offset = log.tell()
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(pathlib.Path(__file__).resolve()),
                    "start",
                    *flags,
                ],
                cwd=ROOT,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        for _ in range(600):
            if process.poll() is not None:
                raise log_error(
                    f"Station startup failed ({process.returncode}).",
                    LOCAL / "logs/supervisor.log",
                    offset,
                )
            state = LOCAL / "station.json"
            if (
                state.exists()
                and json.loads(state.read_text()).get("pid") == process.pid
            ):
                mode = "Receive-only" if args.receive_only else "Transmit-enabled"
                print(
                    f"{mode} station ready: "
                    f"http://127.0.0.1:{config()['http_port']}/ui\n"
                    "Stop the station with mise run stop"
                )
                return
            time.sleep(0.1)
        raise log_error(
            "Station startup still pending after 60 seconds.",
            LOCAL / "logs/supervisor.log",
            offset,
        )
    else:
        options = {"diagnostics": True} if args.diagnostics else {}
        run_stack(transmit=not args.receive_only, modem=args.modem, **options)


if __name__ == "__main__":
    run_cli(main)
