import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import doctor
from station_config import config


class SelectedModemHealth(unittest.TestCase):
    def test_checks_selected_listener_and_processes_without_attaching_modem(self):
        for modem, transport in (("vara", "varahf"), ("ardop", "ardop")):
            with self.subTest(modem=modem), tempfile.TemporaryDirectory() as folder:
                local = Path(folder)
                (local / "station.json").write_text(
                    json.dumps(
                        {
                            "modem": modem,
                            "transmit": False,
                            "pid": 10,
                            "children": {modem: 11},
                        }
                    )
                )
                with (
                    patch("doctor.LOCAL", local),
                    patch("doctor.verify_audio_devices", return_value={}),
                    patch("doctor.sd.check_input_settings"),
                    patch("doctor.sd.check_output_settings"),
                    patch("doctor.os.kill") as alive,
                    patch("doctor.urllib.request.urlopen"),
                    patch(
                        "doctor.json.load",
                        return_value={"active_listeners": [transport]},
                    ),
                    patch(
                        "doctor.subprocess.check_output",
                        return_value="7100000\nPKTUSB\n2800\n0",
                    ),
                    patch(
                        "doctor.operating_state",
                        return_value={"MD": "6", "DT": "0", "BW": "0280", "TQ": "0"},
                    ),
                    contextlib.redirect_stdout(io.StringIO()) as output,
                ):
                    doctor.main()
                self.assertEqual(
                    [call.args for call in alive.call_args_list], [(10, 0), (11, 0)]
                )
                self.assertEqual(json.loads(output.getvalue())["modem"], modem)

    def test_receive_check_uses_active_ardop_for_qsy(self):
        import receive_check

        with (
            patch("receive_check.active_modem", return_value="ardop"),
            patch("receive_check.urllib.request.urlopen") as request,
            patch("receive_check.json.load", return_value={}),
        ):
            receive_check.qsy(7100)
        self.assertEqual(
            json.loads(request.call_args.args[0].data),
            {"transport": "ardop", "freq": 7100},
        )
        self.assertEqual(
            request.call_args.args[0].full_url,
            f"http://127.0.0.1:{config()['http_port']}/api/qsy",
        )
