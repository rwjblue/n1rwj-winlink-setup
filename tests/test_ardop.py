"""Real Besra host/PHY, simulated air and stubbed playback; never radio/audio I/O."""

import socket
import struct
import unittest
from unittest.mock import Mock, patch

import numpy as np

from ardop import StationAudio, StationModem, check_health
from hfmodem.besra.arq.modem import BesraModem
from hfmodem.besra.host.server import HostServer
from hfmodem.besra.sim.air import StepAir
from station_config import config
from cli import UserError


class ReceiveOnly(unittest.TestCase):
    def test_tcp_commands_cannot_key_connect_or_play_audio(self):
        modem = StationModem(threaded=True)
        modem.audio_out = Mock(side_effect=AssertionError("Unexpected audio"))
        server = HostServer(modem, control_port=0, quiet=True)
        server.start()
        self.addCleanup(server.stop)
        with (
            socket.create_connection(("127.0.0.1", server.control_port), 2) as cmd,
            socket.create_connection(("127.0.0.1", server.data_port), 2) as data,
        ):
            pending = b""
            lines = []

            def until(prefix):
                nonlocal pending
                while True:
                    while b"\r" not in pending:
                        chunk = cmd.recv(4096)
                        self.assertTrue(chunk)
                        pending += chunk
                    raw, pending = pending.split(b"\r", 1)
                    line = raw.decode()
                    lines.append(line)
                    self.assertNotEqual(line, "PTT TRUE")
                    if line.startswith(prefix):
                        return line

            cmd.sendall(b"MYCALL N0CALL\rLISTEN TRUE\r")
            until("LISTEN now TRUE")
            self.assertFalse(modem._listen)
            self.assertFalse(modem._session.listen)
            for verb in ("ARQCALL N0TEST 1", "CONNECT N0TEST", "SENDID", "TWOTONETEST"):
                cmd.sendall(verb.encode() + b"\r")
                until("FAULT ")
            data.sendall(struct.pack(">H", 4) + b"mail")
            until("STATUS Receive-only: outbound data refused")
            cmd.sendall(b"VERSION\r")
            until("VERSION ")
            self.assertFalse(modem.connected)
            self.assertEqual(modem.queued, 0)
            modem.audio_out.assert_not_called()

    def test_incoming_real_connect_frame_is_passive(self):
        receiver = StationModem()
        receiver.set_mycall("N0TEST")
        receiver.set_listen(True)
        observer = Mock()
        receiver.start(observer)
        self.addCleanup(receiver.stop)
        receiver.audio_out = Mock()
        caller = BesraModem()
        caller.set_mycall("N0CALL")
        caller.start(Mock())
        self.addCleanup(caller.stop)
        caller.audio_out = receiver.receive_audio
        caller.connect("N0TEST", 1)
        receiver.audio_out.assert_not_called()
        observer.modem_ptt.assert_not_called()
        self.assertFalse(receiver.connected)

    def test_audio_sink_independently_refuses_before_any_device_access(self):
        modem = StationModem(transmit=True)
        with patch("ardop.play_drained") as play:
            StationAudio(modem, config())
            with self.assertRaises(PermissionError):
                modem._emit_samples(np.ones(1200, dtype=np.int16))
        play.assert_not_called()


class AudioPath(unittest.TestCase):
    def test_peer_closing_id_precedes_disconnected_and_abort_cancels_it(self):
        for abort in (False, True):
            with self.subTest(abort=abort):
                events = []
                observer = Mock()
                observer.modem_ptt.side_effect = lambda on: events.append(("ptt", on))
                observer.modem_disconnected.side_effect = lambda: events.append(
                    ("disconnected", None)
                )
                modem = StationModem(transmit=True)
                modem.set_mycall("N0CALL")
                modem.start(observer)
                observer.modem_newstate.reset_mock()
                modem.audio_out = lambda samples: events.append(("audio", True))
                try:
                    modem._identify_on_close("peer_disc")
                    modem._observer.modem_disconnected()
                    modem._observer.modem_newstate("DISC")
                    observer.modem_disconnected.assert_not_called()
                    observer.modem_newstate.assert_not_called()
                    modem.tick(4)
                    self.assertEqual(events, [])
                    if abort:
                        modem.abort()
                        modem.tick(6)
                        self.assertEqual(events, [("disconnected", None)])
                    else:
                        modem.tick(6)
                        self.assertEqual(
                            events,
                            [
                                ("ptt", True),
                                ("audio", True),
                                ("ptt", False),
                                ("disconnected", None),
                            ],
                        )
                    self.assertFalse(modem.identification_pending)
                    observer.modem_newstate.assert_called_once_with("DISC")
                finally:
                    modem.stop()

    def test_forced_bandwidth_is_rejected_instead_of_silently_calling_max(self):
        modem = StationModem(transmit=True)
        with self.assertRaisesRegex(ValueError, "MAX"):
            modem.set_bandwidth(2000, True)

    def test_real_12khz_frame_uses_limited_stereo_48khz_between_ptt_edges(self):
        events = []
        modem = StationModem(transmit=True)
        cfg = config() | {"ptt_lead_seconds": 0, "tx_tail_seconds": 0}
        # No recorder or capture device is opened in this test.
        audio = StationAudio(modem, cfg)
        audio.transmit_enabled = True
        observer = Mock()
        observer.modem_ptt.side_effect = lambda on: events.append(("ptt", on))
        modem.set_mycall("N0CALL")
        modem.start(observer)
        self.addCleanup(modem.stop)

        def playback(samples, rate, device):
            events.append(("audio", True))
            self.assertTrue(audio.muted)
            self.assertEqual(rate, 48000)
            self.assertEqual(device, cfg["tx_device"])
            self.assertEqual(samples.shape[1], 2)
            np.testing.assert_array_equal(samples[:, 0], samples[:, 1])
            self.assertLessEqual(
                float(np.max(np.abs(samples))), cfg["amplitude"] + 1e-7
            )

        with patch("ardop.play_drained", side_effect=playback):
            modem.connect("N0TEST", 1)
        self.assertEqual(events, [("ptt", True), ("audio", True), ("ptt", False)])
        self.assertFalse(audio.muted)
        self.assertEqual(audio.bursts_sent, 1)

    def test_retirement_and_playback_failure_always_release_ptt(self):
        for retired in (False, True):
            with self.subTest(retired=retired):
                modem = StationModem(transmit=True)
                audio = StationAudio(modem, config())
                audio.transmit_enabled = True
                if retired:
                    audio.retiring.set()
                observer = Mock()
                modem.start(observer)
                try:
                    with (
                        patch(
                            "ardop.play_drained", side_effect=OSError("output failed")
                        ) as play,
                        self.assertRaises((OSError, PermissionError)),
                    ):
                        modem._emit_samples(np.ones(1200, dtype=np.int16))
                    self.assertEqual(
                        observer.modem_ptt.call_args_list[-1].args, (False,)
                    )
                    self.assertFalse(audio.muted)
                    if retired:
                        play.assert_not_called()
                finally:
                    modem.stop()

    def test_dead_audio_or_timer_makes_process_health_fail(self):
        for part in ("timer", "receiver", "stream", "host"):
            modem, audio, server = Mock(), Mock(), Mock()
            modem._pump.is_alive.return_value = part != "timer"
            audio._pump.is_alive.return_value = part != "receiver"
            audio._stream.active = part != "stream"
            server._running = part != "host"
            with self.subTest(part=part), self.assertRaisesRegex(UserError, "ARDOP"):
                check_health(modem, audio, server)


class SimulatedAir(unittest.TestCase):
    def test_station_modems_connect_transfer_and_disconnect_over_real_waveforms(self):
        air = StepAir()
        caller = StationModem(transmit=True)
        peer = StationModem(transmit=True)
        ca, pa = Mock(), Mock()
        for modem, call, observer in ((caller, "N0CALL", ca), (peer, "N0TEST", pa)):
            modem.set_mycall(call)
            modem.set_listen(True)
            modem.start(observer)
            self.addCleanup(modem.stop)
            air.join(modem)
        caller.connect("N0TEST")
        air.run()
        self.assertTrue(caller.connected)
        self.assertTrue(peer.connected)
        payload = b"Winlink ARDOP station offline verification"
        caller.transmit(payload)
        air.run()
        received = b"".join(
            c.args[1]
            for c in pa.modem_data_received.call_args_list
            if c.args[0] == "ARQ"
        )
        self.assertEqual(received, payload)
        caller.disconnect()
        air.run(max_time=30, quiet_ticks=400)
        self.assertFalse(caller.connected)
        self.assertFalse(peer.connected)
        ca.modem_disconnected.assert_called_once()
        pa.modem_disconnected.assert_called_once()
