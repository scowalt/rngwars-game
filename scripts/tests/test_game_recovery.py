import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import test_sqlite_backup as backup_fixtures


TOOL = Path(__file__).parents[1] / "game_recovery.py"


class DeploymentRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture = backup_fixtures.ResticOperatorTests()
        previous = os.umask(0o077)
        try:
            fixture.setUp()
        finally:
            os.umask(previous)
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.root = fixture.root
        fixture.writer.execute("PRAGMA application_id=1380861783")
        fixture.writer.commit()
        fixture.success(fixture.command("init", env=fixture.env))
        self.runtime = self.root / "runtime.env"
        self.runtime.write_text("".join(key + "=" + value + "\n" for key, value in fixture.env.items() if key not in {"PATH", "TZ"}))
        self.runtime.chmod(0o600)
        self.area = self.root / "deployment"
        self.area.mkdir(mode=0o700)

    def command(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *map(str, args)], env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=90)

    def test_captures_encrypted_recovery_without_retention_or_changing_live_records(self):
        before = self.fixture.command("snapshots", env=self.fixture.env).stdout
        result = self.command("capture", self.fixture.db, self.area, "--environment", self.runtime)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertTrue(value["encrypted_restore_verified"])
        self.assertFalse(value["retention_run"])
        self.fixture.success(self.fixture.command("verify", self.fixture.db, self.area / "restored.sqlite3"))
        for snapshot in before.splitlines():
            if len(snapshot) == 64:
                self.assertIn(snapshot, self.fixture.command("snapshots", env=self.fixture.env).stdout)
        self.assertNotIn("synthetic-sensitive-token", result.stdout + result.stderr)
        self.assertNotEqual(self.command("capture", self.fixture.db, self.area, "--environment", self.runtime).returncode, 0)


if __name__ == "__main__":
    unittest.main()
