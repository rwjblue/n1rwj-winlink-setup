import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pat_config
from station_config import ROOT


class ProjectPatConfiguration(unittest.TestCase):
    def test_fresh_station_needs_no_ignored_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(
                ROOT / "config",
                root / "config",
                ignore=shutil.ignore_patterns("*.local.*"),
            )
            generated = json.loads(pat_config.configure(root).read_text())
            self.assertEqual(generated["mycall"], "N1RWJ")
            self.assertEqual(generated["locator"], "FN41fr")
            self.assertEqual(generated["secure_login_password"], "")
            self.assertEqual(generated["varahf"]["rig"], "qk4")
            self.assertTrue(generated["varahf"]["ptt_ctrl"])
            self.assertTrue((root / ".local/logs").is_dir())
            self.assertEqual(
                (root / ".local/pat/config.json").stat().st_mode & 0o777, 0o600
            )

    def test_source_changes_replace_stale_runtime_config_with_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(
                ROOT / "config",
                root / "config",
                ignore=shutil.ignore_patterns("*.local.*"),
            )
            target = pat_config.configure(root)
            stale = json.loads(target.read_text())
            stale["mycall"] = "STALE"
            target.write_text(json.dumps(stale))
            (root / "config/station.local.toml").write_text(
                'callsign = "N0TEST"\nlocator = "AA00aa"\nhttp_port = 18080\nrigctld_port = 14532\n'
            )
            with patch("pat_config.Path.home", return_value=root / "home"):
                actual = json.loads(pat_config.configure(root).read_text())
            self.assertEqual(actual["mycall"], "N0TEST")
            self.assertEqual(actual["locator"], "AA00aa")
            self.assertEqual(actual["http_addr"], "127.0.0.1:18080")
            self.assertEqual(actual["hamlib_rigs"]["qk4"]["address"], "127.0.0.1:14532")
            backups = list(
                (
                    root
                    / "home/Library/Application Support/n1rwj-winlink-setup/backups"
                ).glob("*.json")
            )
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text()), stale)

    def test_home_environment_cannot_redirect_project_rig_or_identity(self):
        with (
            patch("pat_config.credential_overrides", return_value={}),
            patch.dict(
                os.environ,
                {
                    "PAT_MYCALL": "WRONG",
                    "PAT_HAMLIB_RIGS_qk4_ADDRESS": "elsewhere:9299",
                    "PAT_STATION_QSY_HOOK": "/elsewhere/untrusted-hook",
                    "PAT_SECURE_LOGIN_PASSWORD": "test-only-placeholder",
                    "XDG_DATA_HOME": "/elsewhere",
                },
            ),
        ):
            env = pat_config.pat_environment()
            self.assertNotIn("PAT_MYCALL", env)
            self.assertNotIn("PAT_HAMLIB_RIGS_qk4_ADDRESS", env)
            self.assertEqual(env["PAT_STATION_QSY_HOOK"], str(ROOT / "bin/pat-qsy"))
            self.assertEqual(env["PAT_SECURE_LOGIN_PASSWORD"], "test-only-placeholder")
            self.assertEqual(env["XDG_DATA_HOME"], str(ROOT / ".local"))
            self.assertEqual(os.environ["XDG_DATA_HOME"], "/elsewhere")

    def test_launcher_always_uses_the_station_pat_build(self):
        with (
            patch(
                "pat_config.ensure_pat", return_value=ROOT / ".cache/pat-station/pat"
            ),
            patch("pat_config.configure", return_value=ROOT / ".local/pat/config.json"),
        ):
            args = pat_config.pat_args()
        self.assertEqual(args[0], str(ROOT / ".cache/pat-station/pat"))


class WinlinkCredentials(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        shutil.copytree(
            ROOT / "config",
            self.root / "config",
            ignore=shutil.ignore_patterns("*.local.*"),
        )
        self.patch_root = patch("pat_config.ROOT", self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.patch_env = patch.dict(os.environ, {}, clear=True)
        self.patch_env.start()
        self.addCleanup(self.patch_env.stop)

    def test_dotenv_credentials_reach_only_pat_environment_and_not_json(self):
        password = "test p a$$#${literal}$(false)"
        (self.root / ".env").write_text(
            f"WINLINK_EMAIL=n1rwj@winlink.org\nWINLINK_PASSWORD='{password}'\n"
        )
        env = pat_config.pat_environment()
        self.assertEqual(env["PAT_MYCALL"], "N1RWJ")
        self.assertEqual(env["PAT_SECURE_LOGIN_PASSWORD"], password)
        self.assertNotIn("WINLINK_PASSWORD", env)
        self.assertNotIn("PAT_SECURE_LOGIN_PASSWORD", os.environ)
        target = pat_config.configure(self.root)
        self.assertEqual(json.loads(target.read_text())["secure_login_password"], "")
        self.assertNotIn(password, target.read_text())

    def test_no_dotenv_is_required_for_receive_only_configuration(self):
        self.assertNotIn("PAT_SECURE_LOGIN_PASSWORD", pat_config.pat_environment())

    def test_explicit_environment_credentials_override_dotenv(self):
        (self.root / ".env").write_text(
            "WINLINK_EMAIL=N1RWJ@winlink.org\nWINLINK_PASSWORD='file-value'\n"
        )
        with patch.dict(os.environ, {"WINLINK_PASSWORD": "environment-value"}):
            self.assertEqual(
                pat_config.pat_environment()["PAT_SECURE_LOGIN_PASSWORD"],
                "environment-value",
            )
        with patch.dict(os.environ, {"PAT_SECURE_LOGIN_PASSWORD": "native-override"}):
            self.assertEqual(
                pat_config.pat_environment()["PAT_SECURE_LOGIN_PASSWORD"],
                "native-override",
            )

    def test_login_identity_mismatch_fails_without_echoing_credentials(self):
        (self.root / ".env").write_text(
            "WINLINK_EMAIL=N0OTHER@winlink.org\nWINLINK_PASSWORD='test-only-secret'\n"
        )
        with self.assertRaises(ValueError) as raised:
            pat_config.pat_environment()
        self.assertIn("match callsign", str(raised.exception))
        self.assertNotIn("N0OTHER", str(raised.exception))
        self.assertNotIn("test-only-secret", str(raised.exception))
