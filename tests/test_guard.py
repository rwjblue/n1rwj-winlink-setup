import asyncio
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import unittest

from cat_guard import Guard, allowed
from station_config import ROOT


class Policy(unittest.TestCase):
    def test_default_refuses_every_transmit_variant(self):
        for command in (
            b"TX",
            b"TX1",
            b"TX/",
            b"TQ1",
            b"TUNE",
            b"SWH16",
            b"PS0",
            b"FA1;TX",
            b"KY TEST",
            b"PC005",
        ):
            self.assertFalse(allowed(command), command)
        self.assertTrue(allowed(b"TX", True))
        self.assertFalse(allowed(b"TX/", True))
        for command in (b"PC005", b"PC050L", b"PC050H"):
            self.assertFalse(allowed(command, True))

    def test_status_and_frequency_commands(self):
        for command in (
            b"FA",
            b"TQ",
            b"IF",
            b"RVM",
            b"FA00014012300",
            b"MD2",
            b"MD6",
            b"DT0",
            b"BW0280",
            b"RX",
        ):
            self.assertTrue(allowed(command), command)
        for command in (b"DT4", b"DT0;TX", b"DT$0", b"TS1", b"TS/"):
            self.assertFalse(allowed(command), command)


class Ownership(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received = []
        self.disconnected = asyncio.Event()

        async def radio(reader, writer):
            try:
                while data := await reader.readuntil(b";"):
                    self.received.append(data)
                    if data == b"FA;":
                        writer.write(b"FA00014012300;")
                        await writer.drain()
            except asyncio.IncompleteReadError:
                pass
            finally:
                writer.close()
                self.disconnected.set()

        self.radio = await asyncio.start_server(radio, "127.0.0.1", 0)
        self.guard = Guard(
            "127.0.0.1",
            self.radio.sockets[0].getsockname()[1],
            transmit=True,
            max_key=0.15,
        )
        self.proxy = await asyncio.start_server(
            self.guard.session, "127.0.0.1", 0, limit=128
        )
        self.reader, self.writer = await asyncio.open_connection(
            "127.0.0.1", self.proxy.sockets[0].getsockname()[1]
        )

    async def asyncTearDown(self):
        self.writer.close()
        for session in list(self.guard.sessions):
            session.cancel()
        await asyncio.gather(*self.guard.sessions, return_exceptions=True)
        self.proxy.close()
        self.radio.close()
        await self.proxy.wait_closed()
        await self.radio.wait_closed()

    async def test_receive_only_and_fragmented_commands(self):
        self.guard.transmit = False
        self.writer.write(b"T")
        await self.writer.drain()
        self.writer.write(b"X;FA;")
        await self.writer.drain()
        self.assertEqual(await self.reader.readuntil(b";"), b"?;")
        self.assertEqual(await self.reader.readuntil(b";"), b"FA00014012300;")
        self.assertNotIn(b"TX;", self.received)

    async def test_disconnect_unkeys(self):
        self.writer.write(b"TX;FA;")
        await self.writer.drain()
        await self.reader.readuntil(b";")
        self.writer.close()
        await asyncio.wait_for(self.disconnected.wait(), 1)
        self.assertEqual(self.received, [b"TX;", b"FA;", b"RX;"])

    async def test_deadman_cannot_be_extended_by_rekey(self):
        self.writer.write(b"TX;TX;")
        await self.writer.drain()
        await asyncio.wait_for(self.disconnected.wait(), 1)
        self.assertEqual(self.received, [b"TX;", b"TX;", b"RX;"])

    async def test_supervisor_loss_unkeys(self):
        self.guard.parent = -1
        self.writer.write(b"TX;")
        await self.writer.drain()
        await asyncio.wait_for(self.disconnected.wait(), 1)
        self.assertEqual(self.received, [b"TX;", b"RX;"])

    async def test_oversized_command_closes_session(self):
        self.writer.write(b"X" * 256)
        await self.writer.drain()
        await asyncio.wait_for(self.disconnected.wait(), 1)
        self.assertEqual(self.received, [])


class ProcessShutdown(unittest.IsolatedAsyncioTestCase):
    async def test_sigterm_unkeys_and_exits_with_a_client_still_connected(self):
        received = []
        disconnected = asyncio.Event()

        async def radio(reader, writer):
            try:
                while frame := await reader.readuntil(b";"):
                    received.append(frame)
                    if frame == b"FA;":
                        writer.write(b"FA00007100000;")
                        await writer.drain()
            except asyncio.IncompleteReadError:
                pass
            finally:
                writer.close()
                disconnected.set()

        server = await asyncio.start_server(radio, "127.0.0.1", 0)
        process = writer = None
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                (root / "tools").mkdir()
                (root / "config").mkdir()
                for name in ("cat_guard.py", "station_config.py"):
                    shutil.copy2(ROOT / "tools" / name, root / "tools" / name)
                shutil.copy2(ROOT / "config/station.toml", root / "config/station.toml")
                (root / "config/station.local.toml").write_text(
                    f"qk4_port = {server.sockets[0].getsockname()[1]}\ncat_guard_port = 0\n"
                )
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(root / "tools/cat_guard.py"),
                    "--approved-transmit",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                ready = await asyncio.wait_for(process.stdout.readline(), 3)
                port = int(re.search(rb"port=(\d+)", ready)[1])
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.write(b"TX;FA;")
                await writer.drain()
                await asyncio.wait_for(reader.readuntil(b";"), 1)
                start = time.monotonic()
                process.terminate()
                await asyncio.wait_for(process.wait(), 1)
                await asyncio.wait_for(disconnected.wait(), 1)
                self.assertLess(time.monotonic() - start, 1)
                self.assertEqual(received, [b"TX;", b"FA;", b"RX;"])
                self.assertEqual(process.returncode, 0)
        finally:
            if writer:
                writer.close()
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            server.close()
            await server.wait_closed()
