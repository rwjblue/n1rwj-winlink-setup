import socket
import threading
import time
import types
import unittest
from unittest.mock import Mock

from kestrel import VaraServer, WinlinkRuntime


class WinlinkReceiver(unittest.TestCase):
    def test_closing_id_uses_host_ptt_once_after_the_attempt(self):
        events = []

        class Observer:
            def modem_disconnected(self):
                events.append(("disconnected", None))

            def __getattr__(self, name):
                return lambda *args, **kwargs: None

        audio = types.SimpleNamespace(
            pending_id=True,
            transmit=True,
            receiving=False,
            next_rx_burst=lambda **kwargs: None,
            key=lambda on: events.append(("key", on)),
            tx=lambda samples, **kwargs: events.append(
                ("audio", kwargs.get("identification"))
            ),
        )
        runtime = WinlinkRuntime(audio)
        modem = runtime.modem_factory()
        modem.start(Observer())
        modem.observer.modem_disconnected()
        self.assertEqual(
            events,
            [("key", True), ("audio", True), ("key", False), ("disconnected", None)],
        )
        modem.observer.modem_disconnected()
        self.assertEqual(events[-1], ("disconnected", None))
        self.assertEqual(sum(e[0] == "audio" for e in events), 1)

    def test_arq_station_replacements_keep_passive_varac_decoder_disabled(self):
        runtime = WinlinkRuntime(types.SimpleNamespace(transmit=True))
        modem = runtime.modem_factory()
        self.assertIsNone(modem.station.cq_detector)
        # Host initialization changes bandwidth and LISTEN, both of which
        # replace the ARQ station. The expensive optional decoder must stay off.
        modem.set_bandwidth("500")
        modem.set_listen(True)
        modem.poll()
        self.assertEqual(modem.station.bw, "500")
        self.assertIsNone(modem.station.cq_detector)
        replies = []
        modem.request_heartbeat(lambda: replies.append("IAMALIVE"))
        modem.poll()
        self.assertEqual(replies, ["IAMALIVE"])

    def test_receive_only_connect_fails_without_killing_the_tcp_modem(self):
        audio = types.SimpleNamespace(
            transmit=False,
            receiving=False,
            next_rx_burst=lambda **kwargs: None,
            key=Mock(side_effect=AssertionError("Unexpected key attempt")),
            tx=Mock(side_effect=AssertionError("Unexpected audio transmission")),
        )
        runtime = WinlinkRuntime(audio)
        server = VaraServer(
            cmd_port=0,
            data_port=0,
            modem_factory=runtime.modem_factory,
            iamalive_interval=0.05,
        )
        stopped = threading.Event()
        failures = []

        def owner():
            try:
                while not stopped.wait(0.005):
                    runtime.step(timeout=0)
            except BaseException as error:
                failures.append(error)

        thread = threading.Thread(target=owner)
        thread.start()
        server.start_background()
        try:
            with (
                socket.create_connection(("127.0.0.1", server.cmd_port), 2) as cmd,
                socket.create_connection(("127.0.0.1", server.data_port), 2),
            ):
                pending = b""

                def until(wanted):
                    nonlocal pending
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        if b"\r" not in pending:
                            chunk = cmd.recv(4096)
                            self.assertTrue(chunk, "Modem closed the command socket")
                            pending += chunk
                            continue
                        line, pending = pending.split(b"\r", 1)
                        self.assertNotEqual(line, b"PTT ON")
                        if line == wanted:
                            return
                    self.fail(f"No modem reply {wanted!r}")

                cmd.sendall(b"MYCALL N0CALL\rLISTEN ON\r")
                until(b"WRONG")
                for _ in range(2):
                    cmd.sendall(b"CONNECT N0CALL N0TEST\r")
                    until(b"OK")
                    until(b"DISCONNECTED")
                    # This heartbeat is produced by the audio owner, so a live
                    # TCP thread alone cannot mask the original poll() crash.
                    until(b"IAMALIVE")
                cmd.sendall(b"BW500\rVERSION\r")
                until(b"OK")
                until(b"VERSION 4.9.0.KestrelOpen")
                self.assertFalse(runtime.modem._listen)
                self.assertFalse(runtime.modem._intent_active)
                self.assertEqual(failures, [])
                audio.key.assert_not_called()
                audio.tx.assert_not_called()
        finally:
            server.stop()
            stopped.set()
            thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
