import unittest

from kestrel import StationAudio


class Interlock(unittest.TestCase):
    def test_receive_only_rejects_key_and_samples_before_io(self):
        audio = StationAudio.__new__(StationAudio)
        audio.transmit = False
        with self.assertRaises(PermissionError):
            audio.key(True)
        with self.assertRaises(PermissionError):
            audio.tx([1.0])
