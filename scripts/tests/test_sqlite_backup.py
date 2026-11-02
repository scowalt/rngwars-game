from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / "sqlite-backup.py"


class OperatorFixture(unittest.TestCase):
    def setUp(self):
        self.area = tempfile.TemporaryDirectory()
        self.addCleanup(self.area.cleanup)
        self.root = Path(self.area.name)
        self.db = self.root / "live.sqlite3"
        self.writer = sqlite3.connect(self.db)
        self.addCleanup(self.writer.close)
        self.writer.executescript(
            "PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0;"
            "PRAGMA user_version=2; PRAGMA application_id=9876;"
            "CREATE TABLE Users(Id TEXT PRIMARY KEY, Token TEXT UNIQUE, Rating INTEGER CHECK(Rating>=100), Wins INTEGER DEFAULT 0);"
            "CREATE TABLE Matches(Id TEXT PRIMARY KEY, PlayerId TEXT REFERENCES Users(Id), Roll REAL, Finished TEXT);"
            "CREATE INDEX MatchPlayer ON Matches(PlayerId);"
            "CREATE TABLE Payloads(Id TEXT PRIMARY KEY, Data BLOB) WITHOUT ROWID;"
            "CREATE TABLE SchemaVersions(Id INTEGER PRIMARY KEY, ScriptName TEXT, Applied TEXT);"
            "INSERT INTO Users VALUES('player-1','synthetic-sensitive-token',1234,7);"
            "INSERT INTO Matches VALUES('match-1','player-1',0.625,'2020-01-02');"
            "INSERT INTO Payloads VALUES('blob-1',X'00FF10');"
            "INSERT INTO SchemaVersions VALUES(1,'RNGWars.Api.migrations.001_initial_schema.sql','2020-01-02');"
            "INSERT INTO SchemaVersions VALUES(2,'RNGWars.Api.migrations.002_add_oauth_fields.sql','2020-02-03');"
        )
        self.db.chmod(0o600)

    def command(self, *args, env=None):
        return subprocess.run(
            [sys.executable, str(TOOL), *map(str, args)],
            capture_output=True,
            text=True,
            env=env,
        )

    def success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)


class OperatorTests(OperatorFixture):
    def test_live_snapshot_preserves_committed_wal_and_is_private(self):
        snapshot = self.root / "snapshot.sqlite3"
        self.success(self.command("snapshot", self.db, snapshot))
        self.success(self.command("verify", self.db, snapshot))
        self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
        main_only = self.root / "main-only.sqlite3"
        main_only.write_bytes(self.db.read_bytes())
        main_only.chmod(0o600)
        self.assertNotEqual(self.command("verify", self.db, main_only).returncode, 0)

    def test_verification_detects_changed_records_schema_journal_and_rowids_at_equal_counts(self):
        for change in (
            "UPDATE Users SET Token='different-sensitive-token'",
            "UPDATE SchemaVersions SET Applied='2021-03-04'",
            "CREATE INDEX ChangedSchema ON Users(Rating)",
            "UPDATE Users SET rowid=99",
            "UPDATE Matches SET Roll=0.626",
            "UPDATE Payloads SET Data=X'00FF11'",
            "PRAGMA user_version=3",
        ):
            with self.subTest(change=change):
                copy = self.root / (str(abs(hash(change))) + ".sqlite3")
                self.success(self.command("snapshot", self.db, copy))
                with closing(sqlite3.connect(copy)) as modified, modified:
                    modified.execute(change)
                result = self.command("verify", self.db, copy)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("sensitive-token", result.stdout + result.stderr)


class ResticOperatorTests(OperatorFixture):
    def setUp(self):
        super().setUp()
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.password = self.root / "password"
        self.password.write_text("synthetic-encryption-password\n")
        self.password.chmod(0o600)
        self.repo = self.root / "repository"
        self.policy = self.root / "policy.json"
        self.policy.write_text(json.dumps({"repository": str(self.repo), "host": "fixture-host", "tag": "fixture-backup", "image_repository": "ghcr.io/example/game", "data_directory": str(self.root)}))
        self.policy.chmod(0o600)
        self.env = {
            "PATH": os.environ["PATH"],
            "RESTIC_REPOSITORY": str(self.repo),
            "RESTIC_PASSWORD_FILE": str(self.password),
            "SQLITE_BACKUP_STATE_DIR": str(self.state),
            "SQLITE_BACKUP_POLICY_FILE": str(self.policy),
            "TZ": "UTC",
        }

    def test_encrypted_repository_backup_restore_and_content_verification(self):
        self.success(self.command("init", env=self.env))
        result = self.command("backup", self.db, env=self.env)
        self.success(result)
        snapshot_id = result.stdout.strip().split()[-1]
        restored = self.root / "restored.sqlite3"
        self.success(self.command("restore", snapshot_id, restored, env=self.env))
        self.success(self.command("verify", self.db, restored))
        self.success(self.command("check", env=self.env))
        self.assertEqual(restored.stat().st_mode & 0o777, 0o600)
        wrong = self.root / "wrong-password"
        wrong.write_text("wrong\n")
        wrong.chmod(0o600)
        denied = self.command("check", env={**self.env, "RESTIC_PASSWORD_FILE": str(wrong)})
        self.assertNotEqual(denied.returncode, 0)
        self.assertNotIn("password", denied.stdout + denied.stderr)
        for file in self.repo.rglob("*"):
            if file.is_file():
                self.assertNotIn(b"synthetic-sensitive-token", file.read_bytes())
        self.assertFalse(any(self.state.rglob("*.sqlite3")))

    def fixture_backup(self, directory, timestamp, tag="fixture-backup", host="fixture-host"):
        result = subprocess.run(
            ["restic", "--no-cache", "--json", "backup", "snapshot.sqlite3", "--host", host,
             "--tag", tag, "--time", timestamp.strftime("%Y-%m-%d %H:%M:%S"), "--group-by", "host,tags"],
            cwd=directory, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, "isolated fixture backup failed")
        return next(json.loads(line)["snapshot_id"] for line in result.stdout.splitlines()
                    if json.loads(line).get("message_type") == "summary")

    def test_retention_keeps_seven_days_hourly_thirty_days_daily_across_staging_paths(self):
        self.success(self.command("init", env=self.env))
        anchor = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
        cases = (
            (40, 0, 0, False), (31, 0, 0, False),
            (29, 0, 0, False), (29, 1, 0, True),
            (8, 0, 0, False), (8, 1, 0, True),
            (6, 0, 0, True), (6, 1, 0, True),
            (1, 0, 0, False), (1, 0, 30, True), (1, 1, 0, True),
            (0, 0, 0, False), (0, 0, 30, True),
        )
        expected = set()
        all_ids = set()
        for index, (days, hours, minutes, keep) in enumerate(cases):
            directory = self.root / ("staging-" + str(index))
            directory.mkdir(mode=0o700)
            self.success(self.command("snapshot", self.db, directory / "snapshot.sqlite3"))
            snapshot_id = self.fixture_backup(directory, anchor - timedelta(days=days) + timedelta(hours=hours, minutes=minutes))
            all_ids.add(snapshot_id)
            if keep:
                expected.add(snapshot_id)
        unrelated = self.fixture_backup(directory, anchor - timedelta(days=40), tag="unrelated")
        other_host = self.fixture_backup(directory, anchor - timedelta(days=40), host="other-host")
        self.success(self.command("retain", env=self.env))
        result = self.command("snapshots", env=self.env)
        self.success(result)
        remaining = set(result.stdout.splitlines()[:-1])
        self.assertEqual(remaining, expected)
        for snapshot_id in expected:
            restored = self.root / (snapshot_id + ".sqlite3")
            self.success(self.command("restore", snapshot_id, restored, env=self.env))
            self.success(self.command("verify", self.db, restored))
        result = subprocess.run(["restic", "--no-cache", "--json", "snapshots"], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, "isolated fixture listing failed")
        self.assertEqual({item["id"] for item in json.loads(result.stdout)}, expected | {unrelated, other_host})
        self.success(self.command("check", env=self.env))

    def test_credential_symlink_ancestors_are_rejected_without_diagnostics(self):
        directory = self.root / "credentials"
        directory.mkdir(mode=0o700)
        nested = directory / "nested"
        nested.mkdir(mode=0o700)
        password = nested / "secret"
        password.write_text("sensitive-credential-value")
        password.chmod(0o600)
        link = self.root / "credential-link"
        link.symlink_to(directory, target_is_directory=True)
        result = self.command("init", env={**self.env, "RESTIC_PASSWORD_FILE": str(link / "nested" / "secret")})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.repo.exists())
        self.assertNotIn("sensitive-credential-value", result.stdout + result.stderr)

    def test_symlink_repository_is_rejected_before_writing(self):
        outside = self.root / "other-repository"
        outside.mkdir(mode=0o700)
        self.repo.symlink_to(outside, target_is_directory=True)
        result = self.command("init", env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    def test_failed_snapshot_or_backup_never_creates_output_or_applies_retention(self):
        self.success(self.command("init", env=self.env))
        directory = self.root / "staging"
        directory.mkdir(mode=0o700)
        self.success(self.command("snapshot", self.db, directory / "snapshot.sqlite3"))
        anchor = datetime.now(timezone.utc) - timedelta(days=1)
        old = self.fixture_backup(directory, anchor - timedelta(days=40))
        recent = self.fixture_backup(directory, anchor)
        broken = self.root / "sensitive-invalid-db"
        broken.write_text("sensitive-response-content")
        broken.chmod(0o600)
        absent = self.root / "missing-sensitive-source"
        for source in (broken, absent):
            with self.subTest(source=source.name):
                destination = self.root / "not-published.sqlite3"
                result = self.command("snapshot", source, destination)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(destination.exists())
                result = self.command("backup", source, env=self.env)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("sensitive-", result.stdout + result.stderr)
                self.assertFalse(absent.exists())
        self.assertFalse(any(self.state.rglob("*.sqlite3")))
        result = self.command("snapshots", env=self.env)
        self.success(result)
        self.assertEqual(set(result.stdout.splitlines()[:-1]), {old, recent})

    def test_wrong_password_backup_and_restore_fail_without_data_or_destination(self):
        self.success(self.command("init", env=self.env))
        result = self.command("backup", self.db, env=self.env)
        self.success(result)
        snapshot_id = result.stdout.strip().split()[-1]
        self.password.write_text("different-sensitive-password")
        destination = self.root / "not-restored.sqlite3"
        for args in (("backup", self.db), ("restore", snapshot_id, destination)):
            result = self.command(*args, env=self.env)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr.strip(), "restic operation failed; diagnostics withheld")
            self.assertEqual(result.stdout, "")
            self.assertFalse(destination.exists())
        self.assertFalse(any(self.state.rglob("*.sqlite3")))

    def test_repository_check_detects_corrupted_encrypted_pack_without_diagnostics(self):
        self.success(self.command("init", env=self.env))
        self.success(self.command("backup", self.db, env=self.env))
        pack = next(path for path in (self.repo / "data").rglob("*") if path.is_file())
        data = bytearray(pack.read_bytes())
        data[-1] ^= 1
        pack.chmod(0o600)
        pack.write_bytes(data)
        result = self.command("check", env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr.strip(), "restic operation failed; diagnostics withheld")
        self.assertEqual(result.stdout, "")

    def test_insecure_credentials_and_invalid_arguments_are_withheld(self):
        self.password.chmod(0o644)
        result = self.command("init", env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.repo.exists())
        self.assertNotIn(str(self.password), result.stderr)
        result = self.command("sensitive-response-as-invalid-command")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr.strip(), "invalid invocation")

    def test_existing_or_unrelated_restore_target_is_never_published(self):
        self.success(self.command("init", env=self.env))
        result = self.command("backup", self.db, env=self.env)
        self.success(result)
        snapshot_id = result.stdout.strip().split()[-1]
        existing = self.root / "existing.sqlite3"
        self.success(self.command("snapshot", self.db, existing))
        for command in (("restore", snapshot_id, existing), ("snapshot", self.db, existing)):
            result = self.command(*command, env=self.env)
            self.assertNotEqual(result.returncode, 0)
            self.success(self.command("verify", self.db, existing))
        source = self.root / "unrelated-staging"
        source.mkdir(mode=0o700)
        self.success(self.command("snapshot", self.db, source / "snapshot.sqlite3"))
        unrelated = self.fixture_backup(source, datetime.now(timezone.utc), tag="unrelated")
        target = self.root / "unrelated-restore.sqlite3"
        result = self.command("restore", unrelated, target, env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
