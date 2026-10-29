import unittest

from cli import UserError
from qk4_settings import verify_audio_devices
from station_config import config


class SavedAudioRouting(unittest.TestCase):
    def test_requires_both_configured_loopback_devices_without_exposing_credentials(
        self,
    ):
        cfg = config()
        devices = [
            {
                "name": cfg["rx_device"],
                "input": False,
                "qk4_format_supported": True,
                "id": "rx-cable",
            },
            {
                "name": cfg["tx_device"],
                "input": True,
                "qk4_format_supported": True,
                "id": "tx-cable",
            },
        ]
        correct = {
            "audio.speakerDevice": "rx-cable",
            "audio.micDevice": "tx-cable",
            "audio.micGain": cfg["qk4_mic_gain"],
        }
        self.assertEqual(
            verify_audio_devices(correct, devices),
            {key: value for key, value in correct.items() if key != "audio.micGain"},
        )
        for wrong in (
            correct | {"audio.micDevice": "BuiltInMicrophoneDevice"},
            correct | {"audio.speakerDevice": ""},
            correct | {"audio.micGain": cfg["qk4_mic_gain"] + 1},
            {},
        ):
            with (
                self.subTest(preferences=wrong),
                self.assertRaises(UserError) as error,
            ):
                verify_audio_devices(
                    wrong | {"radios.1.password": "test-secret"}, devices
                )
            self.assertIn("configure-qk4", str(error.exception))
            self.assertNotIn("test-secret", str(error.exception))
            if wrong.get("audio.speakerDevice") != "rx-cable":
                self.assertIn("Speaker/output device", str(error.exception))
                self.assertIn(cfg["rx_device"], str(error.exception))
