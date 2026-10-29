import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import station


class RFStartup(unittest.TestCase):
    def test_qro_power_reaches_startup_without_any_power_override(self):
        cfg = station.config()
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder)
            pat_config = local / "pat.json"
            pat_config.write_text(
                json.dumps(
                    {
                        "varahf": {
                            "addr": "127.0.0.1:8300",
                            "rig": "qk4",
                            "ptt_ctrl": True,
                        },
                        "hamlib_rigs": {
                            "qk4": {
                                "network": "tcp",
                                "address": f"127.0.0.1:{cfg['rigctld_port']}",
                                "VFO": "",
                            }
                        },
                        "listen": ["varahf"],
                        "schedule": {},
                    }
                )
            )
            with (
                patch("station.LOCAL", local),
                patch("station.pat_environment", return_value={}),
                patch("station.verify_audio_devices"),
                patch("station.configure", return_value=pat_config),
                patch("station.native_power", return_value=b"PC050H") as power,
                patch("station.port_open", return_value=False),
                patch(
                    "socket.create_connection",
                    side_effect=ConnectionRefusedError("test stop before launching"),
                ),
                patch("station.subprocess.Popen") as spawn,
                contextlib.redirect_stdout(io.StringIO()) as output,
                self.assertRaisesRegex(ConnectionRefusedError, "test stop"),
            ):
                station.run_stack(transmit=True)
            power.assert_called_once_with()
            spawn.assert_not_called()
            self.assertIn("PC050H (radio controlled)", output.getvalue())
