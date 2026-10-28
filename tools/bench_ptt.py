"""Exercise real Pat and Hamlib against a simulated K4; no radio or audio IO."""

import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path

from hfmodem.kestrel.host.server import VaraServer

from cat_guard import Guard


async def wait_until(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("Bench condition not reached")
        await asyncio.sleep(0.02)


async def main():
    events = []
    keyed = False
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
        b"MD": b"MD2;",
        b"BW": b"BW0280;",
        b"FR": b"FR0;",
        b"FT": b"FT0;",
        b"AI": b"AI0;",
        b"KS": b"KS017;",
    }

    async def radio(reader, writer):
        nonlocal keyed
        try:
            while frame := await reader.readuntil(b";"):
                command = frame[:-1]
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
            cfg = {
                "mycall": "N1RWJ",
                "listen": ["varahf"],
                "schedule": {},
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
                await asyncio.sleep(0.4)
                with (folder / "pat.log").open("w") as log:
                    pat = await asyncio.create_subprocess_exec(
                        shutil.which("pat"),
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
                    )
                    processes.append(pat)
                    await wait_until(
                        lambda: modem._session and modem._session.listening
                    )
                    await asyncio.sleep(0.3)
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
        guard_server.close()
        for task in list(guard.sessions):
            task.cancel()
        await asyncio.gather(*guard.sessions, return_exceptions=True)
        radio_server.close()
        await guard_server.wait_closed()
        await radio_server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
