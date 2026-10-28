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
        with patch.dict(
            os.environ,
            {
                "PAT_MYCALL": "WRONG",
                "PAT_HAMLIB_RIGS_qk4_ADDRESS": "elsewhere:9299",
                "PAT_SECURE_LOGIN_PASSWORD": "test-only-placeholder",
                "XDG_DATA_HOME": "/elsewhere",
            },
        ):
            env = pat_config.pat_environment()
            self.assertNotIn("PAT_MYCALL", env)
            self.assertNotIn("PAT_HAMLIB_RIGS_qk4_ADDRESS", env)
            self.assertEqual(env["PAT_SECURE_LOGIN_PASSWORD"], "test-only-placeholder")
            self.assertEqual(env["XDG_DATA_HOME"], str(ROOT / ".local"))
            self.assertEqual(os.environ["XDG_DATA_HOME"], "/elsewhere")
