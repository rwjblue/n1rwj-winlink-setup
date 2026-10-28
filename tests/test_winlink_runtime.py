import types
import unittest

from kestrel import WinlinkRuntime


class WinlinkReceiver(unittest.TestCase):
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
