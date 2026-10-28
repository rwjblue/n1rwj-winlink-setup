import types
import unittest

from kestrel import WinlinkRuntime


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
        runtime = WinlinkRuntime(types.SimpleNamespace())
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
