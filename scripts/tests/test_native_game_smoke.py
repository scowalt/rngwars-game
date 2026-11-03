from contextlib import closing
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("native_game_smoke", Path(__file__).parents[1] / "native_game_smoke.py")
n = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(n)


class NativeContextTests(unittest.TestCase):
    def test_rejects_local_x86_or_other_repository_execution(self):
        good = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY_ID": "1442331254", "RUNNER_ARCH": "ARM64", "GITHUB_SHA": "a" * 40}
        n.validate_context(good, "aarch64")
        for env, machine in [({}, "aarch64"), (good, "x86_64"), ({**good, "GITHUB_REPOSITORY_ID": "1"}, "aarch64"), ({**good, "GITHUB_SHA": "main"}, "aarch64")]:
            with self.subTest(machine=machine, env=env):
                with self.assertRaises(n.Failed):
                    n.validate_context(env, machine)


class FreshBackupTests(unittest.TestCase):
    def test_empty_initialized_baseline_survives_encrypted_local_backup_and_restore(self):
        with tempfile.TemporaryDirectory() as area:
            root = Path(area)
            source = root / "initialized.db"
            with closing(sqlite3.connect(source)) as connection:
                migrations = sorted((Path(__file__).parents[2] / "apps/api/migrations").glob("*.sql"))
                self.assertEqual(len(migrations), 2)
                for migration in migrations:
                    connection.executescript(migration.read_text())
                connection.executescript("PRAGMA application_id=1380861783; CREATE TABLE SchemaVersions(SchemaVersionID INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, ScriptName TEXT NOT NULL, Applied DATETIME NOT NULL);")
                connection.executemany("INSERT INTO SchemaVersions(ScriptName, Applied) VALUES(?,?)", [("RNGWars.Api.migrations." + migration.name, "2026-01-01 00:00:00") for migration in migrations])
                connection.commit()
            source.chmod(0o600)
            restored = n.encrypted_roundtrip(source, root)
            self.assertEqual(restored.stat().st_mode & 0o777, 0o600)
            with closing(sqlite3.connect(f"file:{restored}?mode=ro", uri=True)) as connection:
                self.assertEqual(connection.execute("PRAGMA application_id").fetchone(), (0x524E4757,))
                self.assertEqual(connection.execute("SELECT count(*) FROM users").fetchone(), (0,))
                self.assertEqual(connection.execute("SELECT count(*) FROM matches").fetchone(), (0,))
            for path in (root / "repository").rglob("*"):
                if path.is_file():
                    self.assertNotIn(b"SQLite format 3", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
