import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "scripts/sqlite-backup.py"
SCHEDULE = ROOT / "scripts/sqlite-backup-schedule.py"


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.area = tempfile.TemporaryDirectory()
        self.addCleanup(self.area.cleanup)
        self.root = Path(self.area.name)
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.password = self.root / "password"
        self.password.write_text("synthetic-password\n")
        self.password.chmod(0o600)
        self.policy = self.root / "policy.json"
        self.policy.write_text(json.dumps({"repository": str(self.root / "repository"), "host": "fixture-host", "tag": "fixture-backup", "image_repository": "ghcr.io/example/game", "data_directory": str(self.root)}))
        self.policy.chmod(0o600)
        self.environment = {"PATH": os.environ["PATH"], "RESTIC_REPOSITORY": str(self.root / "repository"), "RESTIC_PASSWORD_FILE": str(self.password), "SQLITE_BACKUP_STATE_DIR": str(self.state), "SQLITE_BACKUP_POLICY_FILE": str(self.policy)}
        self.config = self.root / "runtime.env"
        self.config.write_text("\n".join(f"{key}={value}" for key, value in self.environment.items() if key != "PATH") + "\n")
        self.config.chmod(0o600)
        self.db = self.root / "game.sqlite3"
        self.writer = sqlite3.connect(self.db)
        self.db.chmod(0o600)
        self.addCleanup(self.writer.close)
        self.writer.executescript("PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; CREATE TABLE Users(Id TEXT, Token TEXT); INSERT INTO Users VALUES('synthetic-user', 'synthetic-token');")
        self.db.chmod(0o600)

    def operator(self, *args):
        return subprocess.run([sys.executable, str(BACKUP), *map(str, args)], env=self.environment, capture_output=True, text=True)

    def schedule(self, *args):
        options = [*map(str, args)]
        if options[0] == "validate":
            options += ["--policy", str(self.policy)]
        return subprocess.run([sys.executable, str(SCHEDULE), *options], env={"PATH": os.environ["PATH"], "RESTIC_PASSWORD": "must-not-inherit"}, capture_output=True, text=True)

    def test_deployment_preflight_rejects_empty_missing_insecure_storage_and_mutable_images(self):
        image = "ghcr.io/example/game@sha256:" + "a" * 64
        good = self.schedule("validate", "--data-directory", self.root, "--image", image)
        self.assertEqual(good.returncode, 0, good.stderr)
        mutable = self.schedule("validate", "--data-directory", self.root, "--image", "ghcr.io/example/game:latest")
        self.assertNotEqual(mutable.returncode, 0)
        self.db.chmod(0o644)
        self.assertNotEqual(self.schedule("validate", "--data-directory", self.root, "--image", image).returncode, 0)
        self.writer.close()
        self.db.unlink()
        self.assertNotEqual(self.schedule("validate", "--data-directory", self.root, "--image", image).returncode, 0)
        self.assertFalse(self.db.exists())
        self.db.touch(mode=0o600)
        self.assertNotEqual(self.schedule("validate", "--data-directory", self.root, "--image", image).returncode, 0)
        self.assertEqual(self.db.stat().st_size, 0)

    def test_recovery_configuration_consumes_secret_management_json_privately_without_overwrite(self):
        credentials = self.root / "credentials"
        credentials.mkdir(mode=0o700)
        secrets = {"RNGWARS_BACKUP_RESTIC_PASSWORD": "synthetic-recovered-password", "RNGWARS_BACKUP_AWS_ACCESS_KEY_ID": "synthetic-access", "RNGWARS_BACKUP_AWS_SECRET_ACCESS_KEY": "synthetic-secret", "RNGWARS_BACKUP_REPOSITORY": str(self.root / "repository")}
        command = [sys.executable, str(SCHEDULE), "configure", "--credentials-directory", str(credentials), "--state", str(self.state), "--policy", str(self.policy)]
        result = subprocess.run(command, input=json.dumps(secrets), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((credentials / "password").read_text().strip(), "synthetic-recovered-password")
        runtime = (credentials / "runtime.env").read_text()
        self.assertIn("AWS_DEFAULT_REGION=auto", runtime)
        self.assertNotIn("RESTIC_PASSWORD=", runtime)
        self.assertEqual((credentials / "password").stat().st_mode & 0o777, 0o600)
        self.assertEqual((credentials / "runtime.env").stat().st_mode & 0o777, 0o600)
        again = subprocess.run(command, input=json.dumps({**secrets, "RNGWARS_BACKUP_RESTIC_PASSWORD": "other"}), text=True, capture_output=True)
        self.assertNotEqual(again.returncode, 0)
        self.assertEqual((credentials / "password").read_text().strip(), "synthetic-recovered-password")
        self.assertNotIn("synthetic", result.stdout + result.stderr + again.stdout + again.stderr)
        invalid = self.root / "invalid-credentials"
        invalid.mkdir(mode=0o700)
        command[command.index("--credentials-directory") + 1] = str(invalid)
        rejected = subprocess.run(command, input=json.dumps({**secrets, "RNGWARS_BACKUP_REPOSITORY": str(self.root / "unrelated-repository")}), text=True, capture_output=True)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(list(invalid.iterdir()), [])

    def test_operator_detects_never_run_stale_and_failed_schedule_without_leaking_credentials(self):
        missing = self.schedule("status", "--state", self.state)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("missing successful run", missing.stdout)
        now = time.time()
        record = self.state / "schedule-status.json"
        record.write_text(json.dumps({"started": now - 7200, "finished": now - 7190, "last_success": now - 7200, "success": True}))
        record.chmod(0o600)
        stale = self.schedule("status", "--state", self.state)
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("missed hourly run", stale.stdout)
        self.assertEqual(self.operator("init").returncode, 0)
        result = self.schedule("run", self.root / "missing.sqlite3", "--environment", self.config)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "missing.sqlite3").exists())
        failed = self.schedule("status", "--state", self.state)
        self.assertIn("last run failed", failed.stdout)
        self.assertNotIn("synthetic", result.stdout + result.stderr + failed.stdout + failed.stderr)

    def test_configuration_rejects_public_symlinked_and_override_credentials(self):
        for content, mode in ((self.config.read_text(), 0o644), (self.config.read_text() + "RESTIC_PASSWORD=synthetic-secret\n", 0o600), (self.config.read_text() + "RESTIC_REPOSITORY=synthetic-secret\n", 0o600)):
            with self.subTest(mode=mode):
                self.config.write_text(content)
                self.config.chmod(mode)
                result = self.schedule("run", self.db, "--environment", self.config)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "repository").exists())
                self.assertNotIn("synthetic", result.stdout + result.stderr)
        link = self.root / "link.env"
        link.symlink_to(self.config)
        self.assertNotEqual(self.schedule("run", self.db, "--environment", link).returncode, 0)

    def test_hourly_unit_runs_as_database_owner_and_allows_backup_supported_timeouts(self):
        service = (ROOT / "ops/production/backup-schedule/rngwars-sqlite-backup.service").read_text()
        timer = (ROOT / "ops/production/backup-schedule/rngwars-sqlite-backup.timer").read_text()
        self.assertIn("User=10001", service)
        self.assertIn("Group=10001", service)
        self.assertIn("UMask=0077", service)
        self.assertIn("/usr/bin/python3 ${helper_directory}/sqlite-backup-schedule.py run ${data_directory}/game.sqlite3 --environment ${credentials_directory}/runtime.env", service)
        self.assertIn("TimeoutStartSec=3h", service)
        self.assertNotIn("EnvironmentFile", service)
        self.assertIn("OnCalendar=*-*-* *:00:00 UTC", timer)
        self.assertIn("Persistent=true", timer)

    def test_scheduled_real_backup_restores_committed_wal_and_reports_success(self):
        self.assertEqual(self.schedule("operator", "--environment", self.config, "init").returncode, 0)
        result = self.schedule("run", self.db, "--environment", self.config)
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = self.operator("snapshots").stdout.splitlines()[0]
        restored = self.root / "restored.sqlite3"
        self.assertEqual(self.operator("restore", snapshot, restored).returncode, 0)
        self.assertEqual(self.operator("verify", self.db, restored).returncode, 0)
        status = self.schedule("status", "--state", self.state)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(status.stdout.strip(), "backup schedule healthy")
        self.assertEqual((self.state / "schedule-status.json").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
