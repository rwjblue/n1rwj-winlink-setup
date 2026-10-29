"""Loopback K4 CAT proxy: explicit command allowlist and bounded PTT ownership.

Pat is the only normal PTT owner, through rigctld. Receive-only is the default.
The supervisor closes this proxy when any stack process exits. A deadman ends
an overlong key independently of Pat, Kestrel and the supervisor.
"""

import argparse
import asyncio
import os
import re
import signal
import time

from station_config import config


# Only status queries and settings needed for VFO A DATA-A and mode restoration.
QUERIES = set(
    "ID IF FA FB MD MD$ BW BW$ DT DT$ FR FT TQ AI K2 K3 RVM RVD RVP OM PS KS RT XT RO PC".split()
)
SETTINGS = re.compile(
    rb"(?:FA\d{8,11}|MD[123456789]|DT[0-3]|BW\d{4}|AI[0-4]|K[234][0-2])"
)


def allowed(command, transmit=False):
    return (
        command.decode("ascii", errors="replace") in QUERIES
        or SETTINGS.fullmatch(command) is not None
        or command == b"RX"
        or (transmit and command == b"TX")
    )


class Guard:
    def __init__(self, host, port, *, transmit=False, max_key=30.0):
        self.host, self.port = host, port
        self.transmit, self.max_key = transmit, max_key
        self.owner = None
        self.sessions = set()
        self.parent = os.getppid()

    async def session(self, reader, writer):
        if self.owner is not None:
            writer.close()
            return
        self.owner = writer
        upstream = None
        tasks = []
        keyed_at = None
        self.sessions.add(asyncio.current_task())
        try:
            remote, upstream = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), 3
            )

            async def commands():
                nonlocal keyed_at
                while frame := await reader.readuntil(b";"):
                    command = frame[:-1].strip()
                    permit = allowed(command, self.transmit)
                    if not permit:
                        print(f"BLOCK {command!r}", flush=True)
                        writer.write(b"?;")
                        await writer.drain()
                        continue
                    print(f"CAT {command.decode()}", flush=True)
                    if command == b"TX":
                        if keyed_at is None:
                            keyed_at = time.monotonic()
                    elif command == b"RX":
                        keyed_at = None
                    upstream.write(command + b";")
                    await upstream.drain()

            async def responses():
                while chunk := await remote.read(4096):
                    writer.write(chunk)
                    await writer.drain()

            async def deadman():
                while True:
                    await asyncio.sleep(0.05)
                    if os.getppid() != self.parent:
                        print(
                            "DEADMAN: supervisor exited; closing CAT session",
                            flush=True,
                        )
                        return
                    if (
                        keyed_at is not None
                        and time.monotonic() - keyed_at >= self.max_key
                    ):
                        print(
                            "DEADMAN: key deadline exceeded; closing CAT session",
                            flush=True,
                        )
                        return

            tasks = [asyncio.create_task(fn()) for fn in (commands, responses, deadman)]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (
            OSError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ) as error:
            print(f"CAT closed: {error}", flush=True)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if upstream:
                # Only unkey our own session. QK4 RX is global, so an idle
                # receive-only session must not interrupt a different operator.
                if keyed_at is not None:
                    upstream.write(b"RX;")
                    try:
                        await asyncio.wait_for(upstream.drain(), 1)
                    except OSError, TimeoutError:
                        pass
                upstream.close()
                # QK4 also unkeys on owner disconnect if the RX write is lost.
            writer.close()
            self.owner = None
            self.sessions.discard(asyncio.current_task())


async def main(args):
    cfg = config()
    guard = Guard(
        cfg["qk4_host"],
        cfg["qk4_port"],
        transmit=args.approved_transmit,
        max_key=args.max_key_seconds or cfg["max_key_seconds"],
    )
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    server = await asyncio.start_server(
        guard.session, "127.0.0.1", cfg["cat_guard_port"], limit=4096
    )
    print(
        f"CAT guard ready; transmit={guard.transmit}; port={server.sockets[0].getsockname()[1]}",
        flush=True,
    )
    async with server:
        await stop.wait()
        # Python 3.14 waits for active clients in Server.__aexit__. Cancel
        # them first so their finally blocks send RX and close upstream CAT.
        # Doing this after __aexit__ deadlocks until the supervisor kills us.
        server.close()
        sessions = list(guard.sessions)
        for task in sessions:
            task.cancel()
        await asyncio.gather(*sessions, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-key-seconds", type=float, help="Optional shorter deadman interval"
    )
    parser.add_argument(
        "--approved-transmit",
        action="store_true",
        help="Only after explicit operator approval",
    )
    args = parser.parse_args()
    if (
        args.max_key_seconds is not None
        and not 0 < args.max_key_seconds <= config()["max_key_seconds"]
    ):
        parser.error(
            "Deadman override must be positive and no longer than the configured maximum"
        )
    asyncio.run(main(args))
