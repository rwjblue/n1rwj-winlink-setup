"""Build pinned Pat with a station hook after each successful QSY.

Go's source overlay keeps the frozen upstream checkout untouched. Refuse an
upstream change to the patched call site instead of silently losing the hook.
"""

import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from station_config import ROOT


def ensure_pat():
    source = (ROOT / ".cache/upstream/pat").resolve()
    output = ROOT / ".cache/pat-station"
    output.mkdir(parents=True, exist_ok=True)
    binary = output / "pat"
    stamp = output / "fingerprint"
    hook = ROOT / "tools/pat_qsy.go"
    inputs = (Path(__file__), hook, ROOT / "upstream.lock.json", ROOT / "mise.toml")
    fingerprint = hashlib.sha256(b"".join(p.read_bytes() for p in inputs)).hexdigest()
    with (output / "build.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if binary.exists() and stamp.exists() and stamp.read_text() == fingerprint:
            return binary
        if not source.is_dir():
            raise SystemExit("Pat source is missing; run mise run setup")
        revision = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip()
        pinned = json.loads((ROOT / "upstream.lock.json").read_text())["pat"]["commit"]
        dirty = subprocess.check_output(
            ["git", "-C", str(source), "status", "--porcelain"], text=True
        )
        if revision != pinned or dirty:
            raise SystemExit("Pat source must be clean and pinned; run mise run setup")
        original = (source / "app/freq.go").read_text()
        call = "\terr = rig.SetFreq(newFreq)\n"
        if original.count(call) != 1:
            raise SystemExit("Pat QSY call site changed; review the station overlay")
        replacement = (
            call + "\tif err == nil {\n\t\terr = stationAfterQSY(newFreq)\n\t}\n"
        )
        patched = output / "freq.go"
        patched.write_text(original.replace(call, replacement))
        connect_source = (source / "app/connect.go").read_text()
        connect_call = "\tctx, cancel := context.WithCancel(context.Background())\n"
        if connect_source.count(connect_call) != 1:
            raise SystemExit(
                "Pat Connect call site changed; review the station overlay"
            )
        # Pat's UI removes freq= after a failed QSY. A subsequent Connect must
        # still verify mode/filter on the current frequency before any dial.
        connect_check = (
            '\tif url.Scheme == MethodVaraHF && url.Params.Get("freq") == "" {\n'
            "\t\tif err := stationAfterQSY(int(currFreq)); err != nil {\n"
            '\t\t\tlog.Printf("Unable to prepare DATA-A: %s", err)\n'
            "\t\t\treturn\n\t\t}\n\t}\n\n"
        )
        patched_connect = output / "connect.go"
        patched_connect.write_text(
            connect_source.replace(connect_call, connect_check + connect_call)
        )
        overlay = output / "overlay.json"
        overlay.write_text(
            json.dumps(
                {
                    "Replace": {
                        str(source / "app/freq.go"): str(patched),
                        str(source / "app/connect.go"): str(patched_connect),
                        str(source / "app/station_qsy.go"): str(hook),
                    }
                }
            )
        )
        go = subprocess.check_output(
            ["mise", "which", "go"], cwd=ROOT, text=True
        ).strip()
        temporary = binary.with_suffix(".tmp")
        print("Building station Pat with the DATA-A QSY hook", file=sys.stderr)
        subprocess.run(
            [
                go,
                "build",
                "-trimpath",
                "-overlay",
                str(overlay),
                "-o",
                str(temporary),
                ".",
            ],
            cwd=source,
            check=True,
        )
        temporary.replace(binary)
        stamp.write_text(fingerprint)
    return binary


if __name__ == "__main__":
    print(ensure_pat())
