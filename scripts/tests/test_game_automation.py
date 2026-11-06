import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile


TOOL = Path(__file__).parents[1] / "game_automation.py"
REVISION = "a" * 40


class AutomaticLineageCLITests(unittest.TestCase):
    def setUp(self):
        self.area = tempfile.TemporaryDirectory()
        self.addCleanup(self.area.cleanup)
        self.root = Path(self.area.name)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        repo = {"id": 1442331254}
        owner = {"id": 1100550}
        self.run = {"id": 42, "workflow_id": 11, "path": ".github/workflows/ci.yml", "repository": repo, "head_repository": repo, "head_sha": REVISION, "head_branch": "main", "event": "push", "run_attempt": 1, "status": "completed", "conclusion": "success", "actor": owner, "triggering_actor": owner, "created_at": now}
        self.api = {"": {"id": 1442331254, "private": False, "default_branch": "main"}, "/git/ref/heads/main": {"object": {"sha": REVISION}}, "/actions/workflows/ci.yml": {"id": 11, "path": ".github/workflows/ci.yml", "state": "active"}, "/actions/runs/42": self.run, "/contents/.github/workflows/ci.yml?ref=" + REVISION: {"type": "file", "sha": "b" * 40}, "/actions/runs/42/attempts/1/jobs?per_page=100": {"total_count": 3, "jobs": [{"name": name, "run_id": 42, "status": "completed", "conclusion": "success", "labels": ["ubuntu-latest"]} for name in ["Build API (F#)", "Build Frontend (SolidJS)", "Portable SQLite backup and deployment preparation"]]}}
        gh = self.root / "gh"
        gh.write_text("#!" + sys.executable + "\nimport json,os,sys\nfrom pathlib import Path\nr=Path(__file__).parent\nassert 'AWS_SECRET_ACCESS_KEY' not in os.environ\nassert sys.argv[1:6]==['api','--hostname','github.com','--method','GET']\nroute=sys.argv[-1].removeprefix('repos/scowalt/rngwars-game')\nif route.endswith('/zip'):sys.stdout.buffer.write((r/'artifact.zip').read_bytes())\nelse:print(json.dumps(json.loads((r/'responses.json').read_text())[route]))\n")
        gh.chmod(0o700)
        self.env = {"PATH": str(self.root) + os.pathsep + os.environ["PATH"], "HOME": str(self.root), "GH_TOKEN": "synthetic-read-token", "AWS_SECRET_ACCESS_KEY": "must-not-forward"}

    def invoke(self, command="ci", run_id=42):
        (self.root / "responses.json").write_text(json.dumps(self.api))
        return subprocess.run([sys.executable, str(TOOL), command, "--run", str(run_id), "--revision", REVISION], env=self.env, capture_output=True, text=True, timeout=15)

    def test_accepts_successful_owner_main_push_CI_without_granting_deployment(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"status": "trusted_main_push_CI", "source_revision": REVISION, "ci_run_id": 42})
        self.assertNotIn("synthetic-read-token", result.stdout + result.stderr)

    def test_fork_PR_manual_or_untrusted_actor_CI_cannot_authorize_automatic_publication(self):
        baseline = dict(self.run)
        for change in [{"event": "pull_request"}, {"event": "workflow_dispatch"}, {"head_repository": {"id": 9}}, {"actor": {"id": 9}}, {"triggering_actor": {"id": 9}}, {"head_branch": "feature"}, {"run_attempt": 2}, {"conclusion": "failure"}, {"created_at": "2000-01-01T00:00:00Z"}]:
            with self.subTest(change=change):
                self.api["/actions/runs/42"] = {**baseline, **change}
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("blocked:", result.stderr)
        self.api["/actions/runs/42"] = baseline
        jobs = self.api["/actions/runs/42/attempts/1/jobs?per_page=100"]["jobs"]
        jobs[0]["labels"] = ["self-hosted"]
        self.assertNotEqual(self.invoke().returncode, 0)

    def publication(self):
        self.api["/actions/workflows/game-publication.yml"] = {"id": 13, "path": ".github/workflows/game-publication.yml", "state": "active"}
        self.api["/actions/runs/77"] = {**self.run, "id": 77, "workflow_id": 13, "path": ".github/workflows/game-publication.yml", "event": "workflow_run"}
        self.api["/actions/runs/77/attempts/1/jobs?per_page=100"] = {"total_count": 4, "jobs": [{"name": name, "run_id": 77, "status": "completed", "conclusion": "success", "labels": ["ubuntu-24.04-arm" if name == "Build and exercise native image" else "ubuntu-24.04"]} for name in ["resolve", "Build and exercise native image", "prepare", "publish"]]}
        receipt = {"status": "game_image_publication_verified", "repository": "scowalt/rngwars-game", "repository_id": 1442331254, "source_revision": REVISION, "source_branch": "main", "workflow_revision": REVISION, "revision": REVISION, "ci_run_id": 42, "publication_run_id": 77, "platform": "linux/arm64", "image_repository": "ghcr.io/scowalt/rngwars-game-releases", "image_digest": "sha256:" + "c" * 64, "config_digest": "sha256:" + "d" * 64, "native_receipt_consistent": True, "attempt_tag": "release-attempt/game-publication/" + REVISION, "ruleset_verification": "effective_never"}
        self.set_receipt(receipt)
        return receipt

    def set_receipt(self, receipt):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            entry = zipfile.ZipInfo("game-publication-verified.json")
            entry.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(entry, json.dumps(receipt))
        raw = stream.getvalue()
        (self.root / "artifact.zip").write_bytes(raw)
        self.api["/actions/runs/77/artifacts?per_page=100"] = {"total_count": 1, "artifacts": [{"id": 78, "name": "game-publication-77-1", "expired": False, "size_in_bytes": len(raw), "digest": "sha256:" + hashlib.sha256(raw).hexdigest(), "workflow_run": {"id": 77, "repository_id": 1442331254, "head_repository_id": 1442331254, "head_sha": REVISION, "head_branch": "main"}}]}

    def test_resolves_exact_successful_automatic_publisher_to_its_main_push_CI(self):
        self.publication()
        result = self.invoke("publication", 77)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"status": "trusted_automatic_release", "controller_revision": REVISION, "ci_run_id": 42, "image_source_revision": REVISION, "image_digest": "sha256:" + "c" * 64, "publication_run_id": 77})

    def test_failed_manual_fork_or_wrong_source_publisher_cannot_supply_an_auto_release(self):
        self.publication()
        original = dict(self.api["/actions/runs/77"])
        for change in [{"event": "workflow_dispatch"}, {"conclusion": "failure"}, {"run_attempt": 2}, {"head_repository": {"id": 9}}, {"actor": {"id": 9}}, {"head_sha": "b" * 40}, {"workflow_id": 99}]:
            with self.subTest(change=change):
                self.api["/actions/runs/77"] = {**original, **change}
                self.assertNotEqual(self.invoke("publication", 77).returncode, 0)
        self.api["/actions/runs/77"] = original
        self.api["/actions/runs/77/attempts/1/jobs?per_page=100"]["jobs"][1]["labels"] = ["ubuntu-24.04"]
        self.assertNotEqual(self.invoke("publication", 77).returncode, 0)

    def test_receipt_must_bind_exact_artifact_CI_image_namespace_and_complete_publication(self):
        original = self.publication()
        for change in [{"ci_run_id": True}, {"publication_run_id": 78}, {"image_repository": "ghcr.io/untrusted/image"}, {"status": "image_published_not_yet_attested"}, {"native_receipt_consistent": False}, {"source_revision": "b" * 40}, {"ruleset_verification": "unknown"}, {"image_digest": "latest"}]:
            with self.subTest(change=change):
                self.set_receipt({**original, **change})
                self.assertNotEqual(self.invoke("publication", 77).returncode, 0)
        self.set_receipt(original)
        artifact = self.api["/actions/runs/77/artifacts?per_page=100"]["artifacts"][0]
        artifact["workflow_run"]["id"] = 79
        self.assertNotEqual(self.invoke("publication", 77).returncode, 0)
        self.set_receipt(original)
        with (self.root / "artifact.zip").open("ab") as stream:
            stream.write(b"changed")
        self.assertNotEqual(self.invoke("publication", 77).returncode, 0)

    def test_stale_main_cannot_be_reintroduced_by_a_successful_old_CI_or_publisher(self):
        self.publication()
        self.api["/git/ref/heads/main"]["object"]["sha"] = "b" * 40
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertNotEqual(self.invoke("publication", 77).returncode, 0)


if __name__ == "__main__":
    unittest.main()
