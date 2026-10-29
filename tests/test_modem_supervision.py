"""Supervise inert child processes without touching a station or audio device."""

import contextlib
import fcntl
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import pat_config
import station
from modems import MODEMS
from station_config import ROOT
from cli import UserError


class ModemSelection(unittest.TestCase):
    def test_ardop_rejects_kestrel_diagnostics_before_starting_or_touching_state(self):
        with (
            patch(
                "sys.argv",
                [
                    "station",
                    "start",
                    "--background",
                    "--modem",
                    "ardop",
                    "--receive-only",
                    "--diagnostics",
                ],
            ),
            patch("station.run_stack") as run,
            patch("station.subprocess.Popen") as spawn,
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaisesRegex(SystemExit, "2"),
        ):
            station.main()
        run.assert_not_called()
        spawn.assert_not_called()
        with (
            patch("station.config") as config,
            self.assertRaisesRegex(UserError, "Kestrel only"),
        ):
            station.run_stack(modem="ardop", diagnostics=True)
        config.assert_not_called()

    def test_detached_vara_diagnostics_preserve_receive_only(self):
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder)
            process = Mock(pid=123)
            process.poll.return_value = None

            def launch(*args, **kwargs):
                (local / "station.json").write_text(json.dumps({"pid": 123}))
                return process

            with (
                patch(
                    "sys.argv",
                    [
                        "station",
                        "start",
                        "--background",
                        "--receive-only",
                        "--diagnostics",
                    ],
                ),
                patch("station.LOCAL", local),
                patch("station.subprocess.Popen", side_effect=launch) as popen,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                station.main()
            self.assertEqual(
                popen.call_args.args[0][-2:], ["--receive-only", "--diagnostics"]
            )

    def test_foreground_and_detached_selection_keep_receive_only(self):
        for receive_only in (True, False):
            flags = ["--modem", "ardop"] + (["--receive-only"] if receive_only else [])
            with (
                patch("sys.argv", ["station", "start", *flags]),
                patch("station.run_stack") as run,
            ):
                station.main()
            run.assert_called_once_with(transmit=not receive_only, modem="ardop")
            with tempfile.TemporaryDirectory() as folder:
                local = Path(folder)
                process = Mock(pid=123)
                process.poll.return_value = None

                def launch(*args, **kwargs):
                    (local / "station.json").write_text(json.dumps({"pid": 123}))
                    return process

                with (
                    patch("sys.argv", ["station", "start", "--background", *flags]),
                    patch("station.LOCAL", local),
                    patch("station.subprocess.Popen", side_effect=launch) as popen,
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    station.main()
                actual = popen.call_args.args[0]
                self.assertEqual(actual[-2:], ["--modem", "ardop"])
                self.assertEqual("--receive-only" in actual, receive_only)

    def test_both_modes_have_one_audio_owner_and_guard_first_cleanup(self):
        for name, selected in MODEMS.items():
            cases = [(True, False), (False, False)]
            if name == "vara":
                cases.append((False, True))
            for transmit, diagnostics in cases:
                with (
                    self.subTest(
                        modem=name, transmit=transmit, diagnostics=diagnostics
                    ),
                    tempfile.TemporaryDirectory() as folder,
                ):
                    root = Path(folder)
                    shutil.copytree(
                        ROOT / "config",
                        root / "config",
                        ignore=shutil.ignore_patterns("*.local.*"),
                    )
                    target = pat_config.configure(root, modem=name)
                    children, shutdown, states = [], [], []

                    def spawn(args, **kwargs):
                        child = Mock(pid=100 + len(children))
                        child.poll.return_value = None
                        child.terminate.side_effect = lambda: shutdown.append(args)
                        children.append((args, child))
                        kwargs["stdout"].write(
                            "CAT guard ready\nKestrel ready\nARDOP ready\n"
                        )
                        kwargs["stdout"].flush()
                        return child

                    def sleep(_):
                        state = root / ".local/station.json"
                        if state.exists():
                            states.append(json.loads(state.read_text()))
                            raise RuntimeError("simulated supervisor failure")

                    with (
                        patch("station.LOCAL", root / ".local"),
                        patch("station.RESOURCE_LOCK", root / "resource.lock"),
                        patch("station.pat_environment", return_value={}),
                        patch("station.verify_audio_devices"),
                        patch("station.native_power", return_value=b"PC050L"),
                        patch("station.configure", return_value=target),
                        patch(
                            "station.pat_args", return_value=["fake-pat"]
                        ) as pat_args,
                        patch(
                            "station.port_open", side_effect=lambda _: bool(children)
                        ),
                        patch("station.socket.create_connection"),
                        patch("station.operating_state", return_value={}),
                        patch("station.select_data_a", return_value={"BW": "0280"}),
                        patch("station.signal.signal"),
                        patch("station.subprocess.Popen", side_effect=spawn),
                        patch("station.time.sleep", side_effect=sleep),
                        contextlib.redirect_stdout(io.StringIO()),
                        self.assertRaisesRegex(
                            RuntimeError, "simulated supervisor failure"
                        ),
                    ):
                        station.run_stack(
                            transmit=transmit, modem=name, diagnostics=diagnostics
                        )
                    audio_args = [
                        args
                        for args, _ in children
                        if any(
                            str(a).endswith(("kestrel.py", "ardop.py")) for a in args
                        )
                    ]
                    self.assertEqual(len(audio_args), 1)
                    self.assertIn(f"tools/{selected['process']}.py", audio_args[0])
                    self.assertEqual("--approved-transmit" in audio_args[0], transmit)
                    self.assertEqual("--diagnostics" in audio_args[0], diagnostics)
                    self.assertEqual("--approved-transmit" in children[0][0], transmit)
                    self.assertEqual(states[0]["modem"], name)
                    self.assertEqual(states[0]["diagnostics"], diagnostics)
                    pat_args.assert_called_once_with(log_name="pat", modem=name)
                    self.assertIn("tools/cat_guard.py", shutdown[0])
                    self.assertEqual(len(shutdown), 4)
                    self.assertFalse((root / ".local/station.json").exists())

    def test_shared_workspace_lock_or_other_modem_port_refuses_before_radio_access(
        self,
    ):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            resource = root / "resource.lock"
            with resource.open("a") as held:
                for locked in (True, False):
                    fcntl.flock(held, fcntl.LOCK_EX if locked else fcntl.LOCK_UN)
                    with (
                        self.subTest(locked=locked),
                        patch("station.LOCAL", root),
                        patch("station.RESOURCE_LOCK", resource),
                        patch(
                            "station.port_open", side_effect=lambda port: port == 8300
                        ),
                        patch("station.configure") as configure,
                        patch("station.verify_audio_devices") as audio,
                        patch("station.native_power") as power,
                        patch("station.select_data_a") as select,
                        patch("station.socket.create_connection") as connect,
                        self.assertRaisesRegex(SystemExit, "running|Port 8300"),
                    ):
                        station.run_stack(transmit=True, modem="ardop")
                    for operation in (configure, audio, power, select, connect):
                        operation.assert_not_called()
