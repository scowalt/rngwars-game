import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("backup_policy", ROOT / "scripts/backup_policy.py")
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


class BackupPolicyTests(unittest.TestCase):
    def setUp(self):
        self.area = tempfile.TemporaryDirectory()
        self.addCleanup(self.area.cleanup)
        self.root = Path(self.area.name)
        self.value = {"repository": str(self.root / "repository"), "host": "fixture-host", "tag": "fixture-backup", "image_repository": "ghcr.io/example/game", "data_directory": str(self.root / "data")}
        self.path = self.root / "policy.json"
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.value))
        self.path.chmod(0o600)

    def test_private_local_policy_has_explicit_identity_without_defaults(self):
        self.assertEqual(POLICY.load_policy(str(self.path)), self.value)
        for field in self.value:
            invalid = dict(self.value)
            invalid.pop(field)
            with self.subTest(field=field), self.assertRaises(POLICY.PolicyError):
                POLICY.validate_policy(invalid)

    def test_remote_policy_cannot_be_installed_as_mutable_local_configuration(self):
        self.value["repository"] = "s3:https://" + "a" * 32 + ".r2.cloudflarestorage.com/fixture-bucket/fixture-prefix"
        self.save()
        self.assertEqual(POLICY.validate_policy(self.value), self.value)
        with self.assertRaises(POLICY.PolicyError):
            POLICY.load_policy(str(self.path))

    def test_public_symlinked_linked_or_duplicate_policy_is_rejected(self):
        self.path.chmod(0o644)
        with self.assertRaises(POLICY.PolicyError):
            POLICY.load_policy(str(self.path))
        self.path.chmod(0o600)
        link = self.root / "link"
        link.symlink_to(self.path)
        with self.assertRaises(POLICY.PolicyError):
            POLICY.load_policy(str(link))
        hardlink = self.root / "hardlink"
        os.link(self.path, hardlink)
        with self.assertRaises(POLICY.PolicyError):
            POLICY.load_policy(str(self.path))
        hardlink.unlink()
        self.path.write_text('{"host":"one","host":"two"}')
        with self.assertRaises(POLICY.PolicyError):
            POLICY.load_policy(str(self.path))

    def test_invalid_namespace_image_paths_and_repository_forms_are_rejected(self):
        cases = [("host", ""), ("tag", "one,two"), ("tag", "a\nsecret"), ("image_repository", "ghcr.io/example/game:latest"), ("image_repository", "https://example.invalid/game"), ("repository", "s3:http://invalid/bucket/prefix"), ("repository", "s3:https://" + "a" * 32 + ".r2.cloudflarestorage.com/fixture-bucket/prefix?token=bad"), ("data_directory", "/private/../other"), ("repository", "relative")]
        for key, value in cases:
            with self.subTest(key=key), self.assertRaises(POLICY.PolicyError):
                POLICY.validate_policy({**self.value, key: value})

    def test_repository_mismatch_and_missing_policy_fail_before_restic_execution(self):
        password = self.root / "password"
        password.write_text("synthetic-password")
        password.chmod(0o600)
        env = {"PATH": os.environ["PATH"], "RESTIC_REPOSITORY": str(self.root / "wrong"), "RESTIC_PASSWORD_FILE": str(password), "SQLITE_BACKUP_STATE_DIR": str(self.root), "SQLITE_BACKUP_POLICY_FILE": str(self.path)}
        command = [sys.executable, str(ROOT / "scripts/sqlite-backup.py"), "init"]
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "wrong").exists())
        env.pop("SQLITE_BACKUP_POLICY_FILE")
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("synthetic-password", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
