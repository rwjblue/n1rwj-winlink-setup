import asyncio
import unittest

from cat_guard import Guard, allowed


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
        ):
            self.assertFalse(allowed(command), command)
        self.assertTrue(allowed(b"TX", True))
        self.assertFalse(allowed(b"TX/", True))

    def test_status_and_frequency_commands(self):
        for command in (
            b"FA",
            b"TQ",
            b"IF",
            b"RVM",
            b"FA00014012300",
            b"MD2",
            b"BW0280",
            b"RX",
        ):
            self.assertTrue(allowed(command), command)


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
