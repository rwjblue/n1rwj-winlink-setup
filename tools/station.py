"""Supervise the station as one unit; default to receive-only."""

import argparse
import fcntl
import json
import os
import pathlib
import shutil
import signal
import socket
import subprocess
import sys
import time

from station_config import ROOT, config

LOCAL = ROOT / ".local"


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.15):
            return True
    except OSError:
        return False


def configure():
    target = LOCAL / "pat/config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        cfg = config()
        template = json.loads((ROOT / "config/pat.json").read_text())
        template["mycall"] = cfg["callsign"]
        template["http_addr"] = f"127.0.0.1:{cfg['http_port']}"
        template["hamlib_rigs"]["qk4"]["address"] = f"127.0.0.1:{cfg['rigctld_port']}"
        target.write_text(json.dumps(template, indent=2) + "\n")
        target.chmod(0o600)
    return target


def pat_args():
    return [
        shutil.which("pat") or "pat",
        "--config",
        str(configure()),
        "--mbox",
        str(LOCAL / "pat/mailbox"),
        "--forms",
        str(LOCAL / "pat/forms"),
        "--event-log",
        str(LOCAL / "logs/pat-events.json"),
        "--log",
        str(LOCAL / "logs/pat.log"),
    ]


def run_stack(transmit=False):
    cfg = config()
    pat_config = json.loads(configure().read_text())
    expected_vara = {"addr": "127.0.0.1:8300", "rig": "qk4", "ptt_ctrl": True}
    expected_rig = {
        "network": "tcp",
        "address": f"127.0.0.1:{cfg['rigctld_port']}",
        "VFO": "",
    }
    if (
        any(pat_config.get("varahf", {}).get(k) != v for k, v in expected_vara.items())
        or pat_config.get("hamlib_rigs", {}).get("qk4") != expected_rig
        or pat_config.get("schedule")
        or pat_config.get("listen") != ["varahf"]
    ):
        raise SystemExit(
            "Pat configuration bypasses the supervised path or enables other listeners/jobs; inspect .local/pat/config.json"
        )
    LOCAL.mkdir(exist_ok=True, mode=0o700)
    (LOCAL / "logs").mkdir(exist_ok=True)
    with (LOCAL / "station.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Station already running")
        for port in (
            cfg["cat_guard_port"],
            cfg["rigctld_port"],
            8300,
            8301,
            cfg["http_port"],
        ):
            if port_open(port):
                raise SystemExit(
                    f"Port {port} is in use; refusing to start a second stack"
                )
        with socket.create_connection((cfg["qk4_host"], cfg["qk4_port"]), timeout=2):
            pass
        stop = LOCAL / "stop-request"
        stop.unlink(missing_ok=True)
        state = LOCAL / "station.json"
        children = []
        handles = []
        stopping = False

        def request_stop(*_):
            nonlocal stopping
            stopping = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, request_stop)

        def spawn(name, args, port, marker=None):
            path = LOCAL / "logs" / f"{name}.log"
            offset = path.stat().st_size if path.exists() else 0
            log = path.open("a")
            handles.append(log)
            process = subprocess.Popen(
                args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT
            )
            children.append((name, process))
            for _ in range(300):
                if any(p.poll() is not None for _, p in children):
                    raise RuntimeError(
                        f"{name} or a dependency exited; see .local/logs"
                    )
                if stopping or stop.exists():
                    raise RuntimeError("Startup cancelled")
                ready = (
                    marker in path.read_text(errors="replace")[offset:]
                    if marker
                    else port_open(port)
                )
                if ready:
                    time.sleep(0.2)
                    print(f"{name} ready", flush=True)
                    return
                time.sleep(0.1)
            raise TimeoutError(f"{name} did not listen on {port}")

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
            spawn(
                "kestrel",
                [sys.executable, "tools/kestrel.py", *flags],
                8300,
                "Kestrel ready",
            )
            spawn(
                "pat",
                [*pat_args(), "http", "--addr", f"127.0.0.1:{cfg['http_port']}"],
                cfg["http_port"],
            )
            state.write_text(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "transmit": transmit,
                        "children": {n: p.pid for n, p in children},
                    },
                    indent=2,
                )
            )
            print(
                f"Station ready; transmit={transmit}; http://127.0.0.1:{cfg['http_port']}",
                flush=True,
            )
            while not stopping and not stop.exists():
                for name, process in children:
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"{name} exited ({process.returncode}); shutting down the station"
                        )
                time.sleep(0.1)
        finally:
            # Close the guarded CAT connection first: explicit RX and owner
            # disconnect unkey even if Pat or the audio process is stuck.
            for name in ("cat-guard", "pat", "kestrel", "rigctld"):
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
    parser.add_argument("command", choices=["start", "stop", "status", "pat"])
    parser.add_argument("--background", action="store_true")
    parser.add_argument(
        "--approved-transmit",
        action="store_true",
        help="Requires prior explicit user approval",
    )
    args, extra = parser.parse_known_args()
    if extra and args.command != "pat":
        parser.error(f"Unexpected arguments: {extra}")
    os.umask(0o077)
    if args.command == "pat":
        raise SystemExit(subprocess.call([*pat_args(), *extra]))
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
        raise SystemExit("Shutdown did not complete; inspect supervisor.log")
    elif args.background:
        if args.approved_transmit:
            parser.error("Transmit sessions must remain in the foreground")
        (LOCAL / "logs").mkdir(parents=True, exist_ok=True)
        with (LOCAL / "logs/supervisor.log").open("a") as log:
            process = subprocess.Popen(
                [sys.executable, str(pathlib.Path(__file__).resolve()), "start"],
                cwd=ROOT,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        for _ in range(600):
            if process.poll() is not None:
                raise SystemExit("Startup failed; inspect .local/logs/supervisor.log")
            state = LOCAL / "station.json"
            if (
                state.exists()
                and json.loads(state.read_text()).get("pid") == process.pid
            ):
                print("Receive-only station ready")
                return
            time.sleep(0.1)
        raise SystemExit("Startup still pending; inspect .local/logs/supervisor.log")
    else:
        run_stack(args.approved_transmit)


if __name__ == "__main__":
    main()
