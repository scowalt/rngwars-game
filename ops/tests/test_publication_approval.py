from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release_gate.py"
SPEC = importlib.util.spec_from_file_location("release_gate", SCRIPT)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.sha = "a" * 40
        self.artifact = b"synthetic-reviewed-artifact"
        self.policy = {"enabled": True, "operations": ["marketing", "publish-game", "deploy-game"], "repository": "example/game", "repository_id": "123", "owner": "example", "ref": "refs/heads/production", "environment": "fixture-release", "image_repository": "ghcr.io/example/game", "platform": "linux/arm64", "required_checks": ["api", "frontend", "backup", "image"]}
        self.context = {"repository": "example/game", "repository_id": "123", "actor": "example", "triggering_actor": "example", "event_name": "workflow_dispatch", "ref": "refs/heads/production", "environment": "fixture-release", "run_attempt": 1, "sha": self.sha, "approved_revision": self.sha, "controller_fence_attested": True, "private_fence_record": "synthetic-private-record", "tag_already_exists": False}
        self.evidence = {"revision": self.sha, "complete": True, "operation": "publish-game", "verified_at": self.now.isoformat(), "checks": {name: "passed" for name in self.policy["required_checks"]}, "artifact_sha256": hashlib.sha256(self.artifact).hexdigest(), "image_repository": "ghcr.io/example/game", "platform": "linux/arm64", "native_build": True}

    def check(self, operation="publish-game", policy=None, context=None, evidence=None):
        return GATE.check(operation, policy or self.policy, context or self.context, evidence or self.evidence, self.now)

    def test_complete_context_is_only_validation_not_permission_or_deployment(self):
        result = self.check()
        self.assertEqual(result["revision"], self.sha)
        self.assertEqual(result["status"], "context validated only; no operation performed")

    def test_disabled_policy_and_unapproved_operation_fail_closed(self):
        for policy in [{**self.policy, "enabled": False}, {**self.policy, "enabled": "true"}, {**self.policy, "operations": []}]:
            with self.assertRaises(GATE.GateError):
                self.check(policy=policy)

    def test_wrong_repository_identity_owner_rerun_actor_event_ref_or_environment_is_rejected(self):
        fields = {"repository": "another/game", "repository_id": "456", "actor": "another", "triggering_actor": "another", "event_name": "pull_request", "ref": "refs/pull/1/merge", "environment": "unprotected", "run_attempt": 2}
        for key, value in fields.items():
            with self.subTest(key=key), self.assertRaises(GATE.GateError):
                self.check(context={**self.context, key: value})

    def test_missing_or_malformed_context_cannot_publish(self):
        for key in ["repository", "repository_id", "actor", "triggering_actor", "event_name", "ref", "environment", "approved_revision"]:
            for value in ["", " ", self.context[key] + "\n"]:
                with self.subTest(key=key), self.assertRaises(GATE.GateError):
                    self.check(context={**self.context, key: value})
        for revision in ["", "a" * 39, "a" * 41, "A" * 40, "g" * 40, self.sha + "\n"]:
            with self.subTest(revision=revision), self.assertRaises(GATE.GateError):
                self.check(context={**self.context, "sha": revision, "approved_revision": revision})

    def test_revision_drift_unfenced_controller_and_existing_tag_are_rejected(self):
        for context in [{**self.context, "approved_revision": "b" * 40}, {**self.context, "controller_fence_attested": False}, {**self.context, "private_fence_record": ""}, {**self.context, "tag_already_exists": True}]:
            with self.assertRaises(GATE.GateError):
                self.check(context=context)

    def test_wrong_native_platform_image_repository_or_revision_is_rejected(self):
        for key, value in [("platform", "linux/amd64"), ("native_build", False), ("image_repository", "ghcr.io/other/image"), ("revision", "b" * 40), ("operation", "deploy-game")]:
            with self.subTest(key=key), self.assertRaises(GATE.GateError):
                self.check(evidence={**self.evidence, key: value})

    def test_missing_incomplete_failed_or_unexpected_checks_are_rejected(self):
        for checks in [{}, {"api": "passed"}, {**self.evidence["checks"], "image": "failed"}, {**self.evidence["checks"], "extra": "passed"}]:
            with self.assertRaises(GATE.GateError):
                self.check(evidence={**self.evidence, "checks": checks})
        with self.assertRaises(GATE.GateError):
            self.check(evidence={**self.evidence, "complete": False})

    def test_stale_future_and_unzoned_evidence_is_rejected(self):
        times = [(self.now - timedelta(days=2)).isoformat(), (self.now + timedelta(seconds=1)).isoformat(), self.now.replace(tzinfo=None).isoformat()]
        for timestamp in times:
            with self.assertRaises(GATE.GateError):
                self.check(evidence={**self.evidence, "verified_at": timestamp})

    def test_deployment_requires_separate_exact_digest_and_recovery_evidence(self):
        digest = "sha256:" + "b" * 64
        evidence = {**self.evidence, "operation": "deploy-game", "published_digest": digest, "recovery_gates_complete": True}
        context = {**self.context, "approved_digest": digest}
        self.assertEqual(self.check("deploy-game", context=context, evidence=evidence)["operation"], "deploy-game")
        for bad in ["", "sha256:bad", "sha256:" + "c" * 64, digest + "\n"]:
            with self.assertRaises(GATE.GateError):
                self.check("deploy-game", context={**context, "approved_digest": bad}, evidence=evidence)
        with self.assertRaises(GATE.GateError):
            self.check("deploy-game", context=context, evidence={**evidence, "recovery_gates_complete": False})

    def test_marketing_requires_exact_approved_asset(self):
        evidence = {**self.evidence, "operation": "marketing"}
        with self.assertRaises(GATE.GateError):
            self.check("marketing", evidence=evidence)
        context = {**self.context, "approved_artifact_sha256": evidence["artifact_sha256"]}
        self.assertEqual(self.check("marketing", context=context, evidence=evidence)["operation"], "marketing")

    def test_cli_checks_actual_artifact_and_withholds_private_input_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            area = Path(directory)
            for name, data in [("policy", self.policy), ("context", self.context), ("evidence", self.evidence)]:
                (area / (name + ".json")).write_text(json.dumps(data))
            artifact = area / "artifact"
            artifact.write_bytes(self.artifact)
            command = [sys.executable, "-W", "error::ResourceWarning", str(SCRIPT), "publish-game", "--policy", str(area / "policy.json"), "--context", str(area / "context.json"), "--evidence", str(area / "evidence.json"), "--artifact", str(artifact)]
            result = subprocess.run(command, env={"PATH": os.environ["PATH"]}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("synthetic-private-record", result.stdout + result.stderr)
            artifact.write_bytes(b"tampered")
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr.strip(), "release gate rejected; protected evidence requires review")
            (area / "evidence.json").unlink()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_only_main_authorized_game_job_can_publish_and_legacy_alternatives_stay_absent(self):
        self.assertFalse((ROOT / "scripts/manual-release.py").exists())
        self.assertFalse((ROOT / ".github/workflows/deploy-production.yml").exists())
        publishers = set()
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            workflow = yaml.safe_load(path.read_text())
            self.assertNotEqual(workflow.get("permissions", {}).get("packages"), "write")
            for name, job in workflow["jobs"].items():
                if job.get("permissions", {}).get("packages") == "write":
                    publishers.add((path.name, name))
                    self.assertEqual(job["environment"], "game-publication")
                    self.assertIn("github.event_name == 'workflow_run'", job["if"])
                    self.assertIn("needs.prepare.outputs.eligible == 'true'", job["if"])
                    self.assertIn("workflow_run.event == 'push'", workflow["jobs"]["resolve"]["if"])
                    self.assertIn("GAME_AUTOMATIC_CD_ENABLED", workflow["jobs"]["resolve"]["if"])
        self.assertEqual(publishers, {("game-publication.yml", "publish")})


if __name__ == "__main__":
    unittest.main()
