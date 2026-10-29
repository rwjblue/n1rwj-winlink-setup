"""Exercise real Pat and Hamlib against a simulated K4; no radio or audio IO."""

import asyncio
import datetime
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
import urllib.error
import urllib.request
import urllib.parse

from hfmodem.kestrel.host.server import VaraServer

from cat_guard import Guard
from build_pat import ensure_pat
from station_config import ROOT


async def wait_until(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("Bench condition not reached")
        await asyncio.sleep(0.02)


async def main():
    binary = await asyncio.to_thread(ensure_pat)
    events = []
    keyed = False
    refuse_mode = False
    recalls = []
    replies = {
        b"PS": b"PS1;",
        b"ID": b"ID017;",
        b"K2": b"K22;",
        b"K3": b"K31;",
        b"OM": b"OM AP-S----4---;",
        b"RVM": b"RVM03.57;",
        b"RVD": b"RVD01.69;",
        b"RVP": b"RVP01.00;",
        b"FA": b"FA00014101500;",
        b"FB": b"FB00014101500;",
        b"MD": b"MD3;",
        b"MD$": b"MD$3;",
        b"DT": b"DT0;",
        b"DT$": b"DT$0;",
        b"BW": b"BW0280;",
        b"BW$": b"BW$0280;",
        b"FR": b"FR0;",
        b"FT": b"FT0;",
        b"RT": b"RT0;",
        b"XT": b"XT0;",
        b"AI": b"AI0;",
        b"KS": b"KS017;",
    }

    async def recall_band():
        # QK4 first serves the new frequency with the old band's cached mode.
        await asyncio.sleep(0.25)
        replies.update({b"MD": b"MD2;", b"DT": b"DT1;", b"BW": b"BW0050;"})

    async def recall_data_profile():
        await asyncio.sleep(0.15)
        replies.update({b"DT": b"DT1;", b"BW": b"BW0250;"})

    async def radio(reader, writer):
        nonlocal keyed
        try:
            while frame := await reader.readuntil(b";"):
                command = frame[:-1]
                if re.fullmatch(rb"FA\d{11}", command):
                    old = int(replies[b"FA"][2:-1])
                    new = int(command[2:])
                    replies[b"FA"] = command + b";"
                    if (old < 10000000) != (new < 10000000):
                        recalls.append(asyncio.create_task(recall_band()))
                for prefix in (b"MD", b"DT", b"BW"):
                    if re.fullmatch(prefix + rb"\d+", command):
                        if refuse_mode:
                            continue
                        if command == b"MD6" and replies[b"MD"] != b"MD6;":
                            recalls.append(asyncio.create_task(recall_data_profile()))
                        replies[prefix] = command + b";"
                if command in (b"TX", b"RX"):
                    keyed = command == b"TX"
                    events.append((command.decode(), time.monotonic()))
                response = (
                    (b"TQ1;" if keyed else b"TQ0;")
                    if command == b"TQ"
                    else replies.get(command, b"")
                )
                writer.write(response)
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()

    processes = []
    modem = VaraServer(host="127.0.0.1", cmd_port=18300, data_port=18301)
    radio_server = await asyncio.start_server(radio, "127.0.0.1", 19299)
    guard = Guard("127.0.0.1", 19299, transmit=True, max_key=0.5)
    guard_server = await asyncio.start_server(guard.session, "127.0.0.1", 19300)
    try:
        modem.start_background()
        with tempfile.TemporaryDirectory(prefix="winlink-bench-") as folder:
            folder = Path(folder)
            (folder / "config").mkdir()
            (folder / "tools").mkdir()
            (folder / "bin").mkdir()
            state = folder / "state/pat"
            state.mkdir(parents=True)
            (state / ".account-confirmed_N1RWJ.json").write_text(
                json.dumps(datetime.datetime.now(datetime.UTC).isoformat())
            )
            (folder / ".venv").symlink_to(ROOT / ".venv", target_is_directory=True)
            for name in ("qk4_cat.py", "station_config.py", "pat_qsy.py", "cli.py"):
                shutil.copy2(ROOT / "tools" / name, folder / "tools" / name)
            shutil.copy2(ROOT / "bin/pat-qsy", folder / "bin/pat-qsy")
            shutil.copy2(ROOT / "config/station.toml", folder / "config/station.toml")
            (folder / "config/station.local.toml").write_text(
                "qk4_port = 19299\nrigctld_port = 14532\n"
            )
            cfg = {
                "mycall": "N1RWJ",
                "listen": ["varahf"],
                "schedule": {},
                "version_reporting_disabled": True,
                "hamlib_rigs": {
                    "bench": {"network": "tcp", "address": "127.0.0.1:14532", "VFO": ""}
                },
                "varahf": {
                    "addr": "127.0.0.1:18300",
                    "bandwidth": 2300,
                    "rig": "bench",
                    "ptt_ctrl": True,
                },
            }
            (folder / "config.json").write_text(json.dumps(cfg))
            with (folder / "rigctld.log").open("w") as log:
                rig = await asyncio.create_subprocess_exec(
                    "rigctld",
                    "-m",
                    "2047",
                    "-C",
                    "cache_timeout=0",
                    "-r",
                    "127.0.0.1:19300",
                    "-T",
                    "127.0.0.1",
                    "-t",
                    "14532",
                    "-P",
                    "RIG",
                    stdout=log,
                    stderr=log,
                )
                processes.append(rig)
                deadline = time.monotonic() + 10
                while True:
                    try:
                        reader, writer = await asyncio.open_connection(
                            "127.0.0.1", 14532
                        )
                        writer.write(b"f\n")
                        await writer.drain()
                        ready = await asyncio.wait_for(reader.readline(), 1)
                        writer.close()
                        if ready.strip() == b"14101500":
                            break
                    except OSError, TimeoutError:
                        pass
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "Bench rigctld not ready: "
                            + (folder / "rigctld.log").read_text()
                        )
                    await asyncio.sleep(0.05)
                with (folder / "pat.log").open("w") as log:
                    pat = await asyncio.create_subprocess_exec(
                        str(binary),
                        "--config",
                        str(folder / "config.json"),
                        "--mbox",
                        str(folder / "mailbox"),
                        "--log",
                        str(folder / "pat-app.log"),
                        "--event-log",
                        str(folder / "events.json"),
                        "http",
                        "--addr",
                        "127.0.0.1:18080",
                        stdout=log,
                        stderr=log,
                        env={
                            k: v
                            for k, v in os.environ.items()
                            if not k.startswith(("PAT_", "WINLINK_"))
                        }
                        | {
                            "PAT_STATION_QSY_HOOK": str(folder / "bin/pat-qsy"),
                            "XDG_CACHE_HOME": str(folder / "cache"),
                            "XDG_DATA_HOME": str(folder / "data"),
                            "XDG_CONFIG_HOME": str(folder / "config"),
                            "XDG_STATE_HOME": str(folder / "state"),
                        },
                    )
                    processes.append(pat)
                    await wait_until(
                        lambda: modem._session and modem._session.listening
                    )
                    await asyncio.sleep(0.3)

                    def qsy(hz):
                        request = urllib.request.Request(
                            "http://127.0.0.1:18080/api/qsy",
                            data=json.dumps(
                                {"transport": "varahf", "freq": hz / 1000}
                            ).encode(),
                            headers={"Content-Type": "application/json"},
                        )
                        with urllib.request.urlopen(request, timeout=35) as response:
                            return json.load(response)

                    for hz in (7100000, 14101500, 14102000):
                        if hz == 14102000:
                            replies[b"BW"] = b"BW0300;"
                        await asyncio.to_thread(qsy, hz)
                        assert replies[b"FA"] == f"FA{hz:011d};".encode()
                        assert replies[b"MD"] == b"MD6;" and replies[b"DT"] == b"DT0;"
                        assert int(replies[b"BW"][2:-1]) >= 280
                        if hz == 14102000:
                            assert replies[b"BW"] == b"BW0300;", (
                                "Preserve a wider RX filter"
                            )
                        assert not events, "QSY must not key the simulated radio"

                    # Native readback refusing DATA-A must make Pat's QSY fail.
                    refuse_mode = True
                    replies[b"MD"] = b"MD2;"
                    try:
                        await asyncio.to_thread(qsy, 7100000)
                    except urllib.error.HTTPError as error:
                        assert error.code == 500, error.code
                    else:
                        raise AssertionError("Pat accepted an unverified mode")
                    assert not events, "Failed QSY must not key"

                    def connect(frequency):
                        url = "varahf:///N0TEST?bw=2300" + frequency
                        with urllib.request.urlopen(
                            "http://127.0.0.1:18080/api/connect?"
                            + urllib.parse.urlencode({"url": url}),
                            timeout=35,
                        ) as response:
                            return response.read()

                    for frequency in ("&freq=7100", ""):
                        try:
                            await asyncio.to_thread(connect, frequency)
                        except urllib.error.HTTPError as error:
                            assert error.code == 500, error.code
                        else:
                            raise AssertionError("Pat dialed without verified DATA-A")
                    assert (
                        "Connecting to N0TEST"
                        not in (folder / "pat-app.log").read_text()
                    )
                    assert not events, "Failed Connect must not key"
                    refuse_mode = False
                    await asyncio.to_thread(qsy, 14101500)

                    start = time.monotonic()
                    modem._session.modem_ptt(True)
                    await wait_until(lambda: keyed, 2)
                    key_delay = events[-1][1] - start
                    start = time.monotonic()
                    modem._session.modem_ptt(False)
                    await wait_until(lambda: not keyed, 2)
                    unkey_delay = events[-1][1] - start
                    modem._session.modem_ptt(True)
                    await wait_until(lambda: keyed, 2)
                    # Stop delivering OFF. The guard must terminate an overlong
                    # key even while Pat and rigctld remain alive.
                    await wait_until(lambda: not keyed, 2)
                    assert [x[0] for x in events] == ["TX", "RX", "TX", "RX"], events
                    print(
                        json.dumps(
                            {
                                "pat_to_cat_key_ms": round(key_delay * 1000, 2),
                                "pat_to_cat_unkey_ms": round(unkey_delay * 1000, 2),
                                "events": [x[0] for x in events],
                                "deadman_unkey": True,
                                "mode": "DATA-A normal (MD6/DT0), Hamlib PKTUSB/2800",
                                "pat_qsy": "40m, 20m and same-band tuning verified",
                                "band_recall": "delayed USB/RTTY and narrow DATA filter corrected",
                                "failed_mode_qsy": "HTTP 500; no keying",
                                "failed_mode_connect": "with and without freq: HTTP 500 before modem dial",
                                "radio": "simulated; no RF or audio devices opened",
                            },
                            indent=2,
                        )
                    )
    finally:
        for process in reversed(processes):
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        modem.stop()
        for task in recalls:
            task.cancel()
        await asyncio.gather(*recalls, return_exceptions=True)
        guard_server.close()
        for task in list(guard.sessions):
            task.cancel()
        await asyncio.gather(*guard.sessions, return_exceptions=True)
        radio_server.close()
        guard_server.close_clients()
        radio_server.close_clients()
        await guard_server.wait_closed()
        await radio_server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
