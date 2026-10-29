import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import station


class StationStartup(unittest.TestCase):
    def test_start_enables_transmission_unless_receive_only_is_requested(self):
        for args, transmit in (([], True), (["--receive-only"], False)):
            with (
                self.subTest(args=args),
                patch("sys.argv", ["station", "start", *args]),
                patch("station.os.umask"),
                patch("station.run_stack") as run_stack,
            ):
                station.main()
            run_stack.assert_called_once_with(transmit=transmit, modem="vara")

    def test_background_start_preserves_mode_in_the_supervisor(self):
        for args, transmit in (([], True), (["--receive-only"], False)):
            with self.subTest(args=args), tempfile.TemporaryDirectory() as folder:
                local = Path(folder)
                process = Mock(pid=12345)
                process.poll.return_value = None

                def spawn(*_args, **_kwargs):
                    (local / "station.json").write_text(
                        json.dumps({"pid": process.pid, "transmit": transmit})
                    )
                    return process

                with (
                    patch("sys.argv", ["station", "start", "--background", *args]),
                    patch("station.LOCAL", local),
                    patch("station.os.umask"),
                    patch("station.subprocess.Popen", side_effect=spawn) as popen,
                    patch("station.run_stack") as run_stack,
                    contextlib.redirect_stdout(io.StringIO()) as output,
                ):
                    station.main()
                self.assertEqual(
                    popen.call_args.args[0],
                    [
                        station.sys.executable,
                        str(Path(station.__file__).resolve()),
                        "start",
                        *args,
                    ],
                )
                self.assertTrue(popen.call_args.kwargs["start_new_session"])
                run_stack.assert_not_called()
                mode = "Transmit-enabled" if transmit else "Receive-only"
                self.assertIn(f"{mode} station ready:", output.getvalue())
                self.assertIn("mise run stop", output.getvalue())


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
                patch("station.RESOURCE_LOCK", local / "resource.lock"),
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
