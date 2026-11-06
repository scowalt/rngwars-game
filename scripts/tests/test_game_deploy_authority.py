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


TOOL = Path(__file__).parents[1] / "game_deploy_authority.py"
REVISION = "a" * 40
TOKEN = "synthetic-transient-job-read-token"


class DeploymentAuthorityCLITests(unittest.TestCase):
    def setUp(self):
        self.area = tempfile.TemporaryDirectory(dir=Path.home())
        self.addCleanup(self.area.cleanup)
        self.root = Path(self.area.name)
        self.policy = {"version": 1, "environment_id": 42, "workflow_blob": "b" * 40, "ci_blob": "c" * 40, "scripts_tree": "d" * 40}
        self.request = {"version": 1, "operation": "deploy", "run_id": 501, "controller_revision": REVISION, "ci_run_id": 502, "image_source_revision": "e" * 40, "image_digest": "sha256:" + "f" * 64, "publication_run_id": 503}
        self.envelope = {"version": 1, "run_id": 501, "github_token": TOKEN}
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        run = {"id": 501, "workflow_id": 333, "repository": {"id": 1442331254}, "head_repository": {"id": 1442331254}, "head_sha": REVISION, "head_branch": "main", "path": ".github/workflows/game-deployment.yml", "event": "workflow_dispatch", "run_attempt": 1, "status": "in_progress", "conclusion": None, "actor": {"id": 1100550}, "triggering_actor": {"id": 1100550}, "created_at": now}
        self.api = {
            "": {"id": 1442331254, "private": False, "default_branch": "main"},
            "/git/ref/heads/main": {"object": {"sha": REVISION}},
            "/actions/workflows/game-deployment.yml": {"id": 333, "path": ".github/workflows/game-deployment.yml", "state": "active"},
            "/actions/runs/501": run,
            "/contents/.github/workflows/game-deployment.yml?ref=" + REVISION: {"type": "file", "sha": "b" * 40},
            "/contents/.github/workflows/ci.yml?ref=" + REVISION: {"type": "file", "sha": "c" * 40},
            "/git/trees/" + REVISION: {"truncated": False, "tree": [{"path": "scripts", "type": "tree", "mode": "040000", "sha": "d" * 40}]},
            "/environments/game-production": {"id": 42, "name": "game-production", "can_admins_bypass": False, "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}, "protection_rules": [{"type": "required_reviewers", "prevent_self_review": False, "reviewers": [{"type": "User", "reviewer": {"id": 1100550}}]}]},
            "/environments/game-production/deployment-branch-policies": {"total_count": 1, "branch_policies": [{"name": "main", "type": "branch"}]},
            "/actions/runs/501/approvals": [{"state": "approved", "user": {"id": 1100550}, "environments": [{"id": 42, "name": "game-production"}]}],
            "/actions/runs/501/attempts/1/jobs?per_page=100": {"total_count": 3, "jobs": [{"name": name, "run_id": 501, "status": status, "conclusion": conclusion, "labels": ["ubuntu-24.04"], "started_at": now} for name, status, conclusion in [("resolve", "completed", "success"), ("Private transport preflight", "completed", "skipped"), ("Deploy verified game release", "in_progress", None)]]},
            "/actions/workflows/ci.yml": {"id": 444, "path": ".github/workflows/ci.yml", "state": "active"},
            "/actions/runs/502": {**run, "id": 502, "workflow_id": 444, "path": ".github/workflows/ci.yml", "event": "push", "status": "completed", "conclusion": "success"},
            "/actions/runs/502/attempts/1/jobs?per_page=100": {"total_count": 3, "jobs": [{"name": name, "run_id": 502, "status": "completed", "conclusion": "success", "labels": ["ubuntu-latest"]} for name in ["Build API (F#)", "Build Frontend (SolidJS)", "Portable SQLite backup and deployment preparation"]]},
        }
        self.artifact = {"id": 504, "name": "game-deployment-request-501-1", "expired": False, "created_at": now, "updated_at": now, "workflow_run": {"id": 501, "repository_id": 1442331254, "head_repository_id": 1442331254, "head_sha": REVISION, "head_branch": "main"}}
        executable = self.root / "gh"
        executable.write_text("#!" + sys.executable + "\nimport json,os,sys\nfrom pathlib import Path\nr=Path(__file__).parent\nassert os.environ['GH_TOKEN']=='" + TOKEN + "'\nassert not any(k in os.environ for k in ['GITHUB_TOKEN','AWS_SECRET_ACCESS_KEY'])\nassert os.environ['HOME']==os.environ['GH_CONFIG_DIR'] and os.environ['HOME']!=str(r)\nassert sys.argv[1:7]==['api','--hostname','github.com','--method','GET','repos/scowalt/rngwars-game'+sys.argv[-1].removeprefix('repos/scowalt/rngwars-game')]\nroute=sys.argv[-1].removeprefix('repos/scowalt/rngwars-game')\nif (r/'fail').exists():\n print('private-provider-diagnostic '+os.environ['GH_TOKEN'],file=sys.stderr); raise SystemExit(1)\nif route=='/actions/artifacts/504/zip': sys.stdout.buffer.write((r/'artifact.zip').read_bytes())\nelif route=='/actions/artifacts/505/zip': sys.stdout.buffer.write((r/'publication.zip').read_bytes())\nelse:\n value=json.loads((r/'responses.json').read_text())[route]\n if route=='/actions/runs/502': (r/'CI-observed').touch()\n if route=='/actions/runs/501' and (r/'cancel-after-ci').exists() and (r/'CI-observed').exists(): value.update(status='completed',conclusion='cancelled')\n print(json.dumps(value))\n")
        executable.chmod(0o700)
        self.environment = {"PATH": str(self.root) + os.pathsep + os.environ["PATH"], "HOME": str(self.root), "GH_TOKEN": "wrong-ambient-token", "GITHUB_TOKEN": "unrelated-token", "AWS_SECRET_ACCESS_KEY": "unrelated-backup-key"}

    def invoke(self, content=None, entries=None, artifact_change=None):
        policy = self.root / "policy.json"
        if not policy.exists():
            policy.write_text(json.dumps(self.policy))
            policy.chmod(0o400)
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, body, mode in entries or [("request.json", content if content is not None else json.dumps(self.request), stat.S_IFREG | 0o600)]:
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = mode << 16
                archive.writestr(info, body)
        raw = data.getvalue()
        (self.root / "artifact.zip").write_bytes(raw)
        artifact = {**self.artifact, "size_in_bytes": len(raw), "digest": "sha256:" + hashlib.sha256(raw).hexdigest(), **(artifact_change or {})}
        self.api["/actions/runs/501/artifacts?per_page=100"] = {"total_count": 1, "artifacts": [artifact]}
        (self.root / "responses.json").write_text(json.dumps(self.api))
        return subprocess.run([sys.executable, str(TOOL), "inspect", "--policy", str(policy)], input=json.dumps(self.envelope), capture_output=True, text=True, env=self.environment, timeout=15)

    def test_selects_exact_reviewed_request_without_executing_or_exporting_credentials(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"status": "reviewed_deployment_request_verified_no_execution", "request": self.request, "artifact_id": 504})
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        self.assertFalse(any(path.name.startswith("attempt-") for path in self.root.iterdir()))

    def test_refuses_changed_controller_code_even_with_a_real_owner_review(self):
        for path, field in [("/contents/.github/workflows/game-deployment.yml?ref=" + REVISION, "sha"), ("/contents/.github/workflows/ci.yml?ref=" + REVISION, "sha"), ("/git/trees/" + REVISION, "tree")]:
            with self.subTest(path=path):
                previous = self.api[path][field]
                self.api[path][field] = "9" * 40 if field == "sha" else [{"path": "scripts", "type": "tree", "mode": "040000", "sha": "9" * 40}]
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("request_controller_contract", result.stderr)
                self.api[path][field] = previous

    def test_requires_unchanged_environment_protection_and_an_active_hosted_deployment_job(self):
        original = json.dumps(self.api)
        for case in ["bypass", "environment-id", "branches", "reviewer", "self-review", "skipped-deploy", "self-hosted", "extra-job", "unfinished-resolve", "active-preflight", "wrong-job-run", "rerun-boolean"]:
            with self.subTest(case=case):
                self.api = json.loads(original)
                environment = self.api["/environments/game-production"]
                jobs = self.api["/actions/runs/501/attempts/1/jobs?per_page=100"]
                if case == "bypass": environment["can_admins_bypass"] = True
                elif case == "environment-id": environment["id"] = 43
                elif case == "branches": self.api["/environments/game-production/deployment-branch-policies"]["branch_policies"][0]["name"] = "*"
                elif case == "reviewer": environment["protection_rules"][0]["reviewers"][0]["reviewer"]["id"] = 9
                elif case == "self-review": environment["protection_rules"][0]["prevent_self_review"] = True
                elif case == "skipped-deploy": jobs["jobs"][-1].update(status="completed", conclusion="skipped")
                elif case == "self-hosted": jobs["jobs"][-1]["labels"] = ["self-hosted"]
                elif case == "extra-job": jobs["total_count"] = 4
                elif case == "unfinished-resolve": jobs["jobs"][0]["conclusion"] = "failure"
                elif case == "active-preflight": jobs["jobs"][1].update(status="in_progress", conclusion=None)
                elif case == "wrong-job-run": jobs["jobs"][-1]["run_id"] = 9
                else: self.api["/actions/runs/501"]["run_attempt"] = True
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Game deployment request blocked:", result.stderr)
        self.api = json.loads(original)

    def test_refuses_writable_linked_or_malformed_policy_before_reading_provider_data(self):
        path = self.root / "policy.json"
        for case in ["writable", "symlink", "hardlink", "unknown-field", "boolean-version", "invalid-pin", "large", "parent-writable"]:
            with self.subTest(case=case):
                if path.exists() or path.is_symlink(): path.unlink()
                value = dict(self.policy)
                if case == "unknown-field": value["command"] = "/bin/sh"
                elif case == "boolean-version": value["version"] = True
                elif case == "invalid-pin": value["scripts_tree"] = "main"
                path.write_text("x" * 9000 if case == "large" else json.dumps(value))
                path.chmod(0o600 if case == "writable" else 0o400)
                if case in {"symlink", "hardlink"}:
                    backing = self.root / (case + "-policy")
                    path.rename(backing)
                    if case == "symlink": path.symlink_to(backing)
                    else: os.link(backing, path)
                if case == "parent-writable": self.root.chmod(0o770)
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("request_policy", result.stderr)
                self.root.chmod(0o700)

    def test_binds_artifact_transport_and_source_and_refuses_client_command_payloads(self):
        for change in [{"expired": True}, {"id": "504"}, {"size_in_bytes": 9000000}, {"digest": "sha256:" + "0" * 64}, {"workflow_run": {**self.artifact["workflow_run"], "id": 9}}, {"workflow_run": {**self.artifact["workflow_run"], "head_repository_id": 9}}, {"workflow_run": {**self.artifact["workflow_run"], "head_sha": "9" * 40}}]:
            with self.subTest(artifact=change):
                result = self.invoke(artifact_change=change)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("request_artifact", result.stderr)
        original = dict(self.request)
        for change in [{"command": "docker run untrusted"}, {"image_digest": "latest"}, {"ci_run_id": True}, {"publication_run_id": "503"}, {"image_source_revision": "main"}, {"operation": "rollback"}, {"run_id": 9}]:
            with self.subTest(request=change):
                self.request = {**original, **change}
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("request_", result.stderr)
        self.request = original

    def test_requires_fresh_successful_same_source_CI_and_a_recent_deployment_job(self):
        original = json.dumps(self.api)
        for case in ["failed-CI", "old-CI", "future-CI", "other-source", "CI-self-hosted", "CI-wrong-run", "old-deploy", "old-job", "naive-time"]:
            with self.subTest(case=case):
                self.api = json.loads(original)
                ci = self.api["/actions/runs/502"]
                if case == "failed-CI": ci["conclusion"] = "failure"
                elif case == "old-CI": ci["created_at"] = "2000-01-01T00:00:00Z"
                elif case == "future-CI": ci["created_at"] = "2999-01-01T00:00:00Z"
                elif case == "other-source": ci["head_sha"] = "9" * 40
                elif case == "CI-self-hosted": self.api["/actions/runs/502/attempts/1/jobs?per_page=100"]["jobs"][0]["labels"] = ["self-hosted"]
                elif case == "CI-wrong-run": self.api["/actions/runs/502/attempts/1/jobs?per_page=100"]["jobs"][0]["run_id"] = 9
                elif case == "old-deploy": self.api["/actions/runs/501"]["created_at"] = "2000-01-01T00:00:00Z"
                elif case == "old-job": self.api["/actions/runs/501/attempts/1/jobs?per_page=100"]["jobs"][-1]["started_at"] = "2000-01-01T00:00:00Z"
                else: ci["created_at"] = "2026-01-01T00:00:00"
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Game deployment request blocked:", result.stderr)
        self.api = json.loads(original)

    def test_refuses_a_run_cancelled_while_its_CI_evidence_is_being_checked(self):
        (self.root / "cancel-after-ci").touch()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("request_authority_changed", result.stderr)

    def test_bounded_input_wait_does_not_leave_an_unfinished_request_hanging(self):
        with subprocess.Popen([sys.executable, str(TOOL), "inspect", "--policy", str(self.root / "unused")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.environment) as process:
            try:
                process.stdin.write(b"{")
                process.stdin.flush()
                process.wait(timeout=8)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn(b"request_timeout", process.stderr.read())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def test_allows_a_new_application_commit_without_changing_pinned_controller_code(self):
        self.api = json.loads(json.dumps(self.api).replace(REVISION, "9" * 40))
        self.request["controller_revision"] = "9" * 40
        self.artifact["workflow_run"]["head_sha"] = "9" * 40
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["request"]["controller_revision"], "9" * 40)

    def test_rejects_unreviewed_other_owner_other_repository_branch_and_rerun_contexts(self):
        original = json.dumps(self.api)
        for change in [{"run_attempt": 2}, {"event": "pull_request"}, {"head_branch": "other"}, {"actor": {"id": 9}}, {"triggering_actor": {"id": 9}}, {"head_repository": {"id": 9}}, {"repository": {"id": 9}}, {"path": ".github/workflows/other.yml"}]:
            with self.subTest(run=change):
                self.api = json.loads(original)
                self.api["/actions/runs/501"].update(change)
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
        for review in [[], [{"state": "rejected", "user": {"id": 1100550}, "environments": [{"id": 42, "name": "game-production"}]}], [{"state": "approved", "user": {"id": 9}, "environments": [{"id": 42, "name": "game-production"}]}]]:
            with self.subTest(review=review):
                self.api = json.loads(original)
                self.api["/actions/runs/501/approvals"] = review
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("request_review", result.stderr)
        self.api = json.loads(original)

    def test_rejects_archive_paths_links_duplicates_large_members_and_duplicate_JSON_fields(self):
        body = json.dumps(self.request)
        entry = ("request.json", body, stat.S_IFREG | 0o600)
        for entries in [[("../request.json", body, stat.S_IFREG | 0o600)], [("request.json", body, stat.S_IFLNK | 0o777)], [entry, ("extra.json", body, stat.S_IFREG | 0o600)], [("request.json", "x" * 9000, stat.S_IFREG | 0o600)], [("request.json", '{"version":1,' + body[1:], stat.S_IFREG | 0o600)]]:
            with self.subTest(entries=[item[0] for item in entries]):
                result = self.invoke(entries=entries)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Game deployment request blocked:", result.stderr)

    def test_suppresses_private_provider_diagnostics_and_token_material(self):
        (self.root / "fail").touch()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("request_provider_unavailable", result.stderr)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        self.assertNotIn("private-provider-diagnostic", result.stdout + result.stderr)
        self.assertFalse(any(TOKEN.encode() in path.read_bytes() for path in self.root.iterdir() if path.name not in {"gh"} and path.is_file()))

    def test_refuses_an_artifact_created_or_replaced_after_the_protected_job_started(self):
        for field in ["created_at", "updated_at"]:
            with self.subTest(field=field):
                result = self.invoke(artifact_change={field: "2999-01-01T00:00:00Z"})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("request_artifact_timing", result.stderr)

    def automatic_mode(self, publication_run=503, config_digest=None):
        self.policy = {key: value for key, value in self.policy.items() if key != "scripts_tree"}
        self.policy["version"] = 2
        self.api["/actions/runs/501"]["event"] = "workflow_run"
        self.api["/environments/game-production"]["protection_rules"] = []
        self.api["/actions/runs/501/approvals"] = []
        inventory = self.api["/actions/runs/501/attempts/1/jobs?per_page=100"]
        inventory["jobs"].pop(1)
        inventory["total_count"] = 2
        self.request["image_source_revision"] = REVISION
        self.request["publication_run_id"] = publication_run
        self.api["/actions/workflows/game-publication.yml"] = {"id": 555, "path": ".github/workflows/game-publication.yml", "state": "active"}
        self.api[f"/actions/runs/{publication_run}"] = {**self.api["/actions/runs/501"], "id": publication_run, "workflow_id": 555, "path": ".github/workflows/game-publication.yml", "status": "completed", "conclusion": "success"}
        self.api[f"/actions/runs/{publication_run}/attempts/1/jobs?per_page=100"] = {"total_count": 4, "jobs": [{"name": name, "run_id": publication_run, "status": "completed", "conclusion": "success", "labels": ["ubuntu-24.04-arm" if name == "Build and exercise native image" else "ubuntu-24.04"]} for name in ["resolve", "Build and exercise native image", "prepare", "publish"]]}
        receipt = {"status": "game_image_publication_verified", "repository": "scowalt/rngwars-game", "repository_id": 1442331254, "source_revision": REVISION, "source_branch": "main", "workflow_revision": REVISION, "revision": REVISION, "ci_run_id": 502, "publication_run_id": publication_run, "platform": "linux/arm64", "image_repository": "ghcr.io/scowalt/rngwars-game-releases", "image_digest": self.request["image_digest"], "config_digest": config_digest or "sha256:" + "c" * 64, "native_receipt_consistent": True, "attempt_tag": "release-attempt/game-publication/" + REVISION, "ruleset_verification": "effective_never"}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            entry = zipfile.ZipInfo("game-publication-verified.json")
            entry.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(entry, json.dumps(receipt))
        raw = stream.getvalue()
        (self.root / "publication.zip").write_bytes(raw)
        self.api[f"/actions/runs/{publication_run}/artifacts?per_page=100"] = {"total_count": 1, "artifacts": [{"id": 505, "name": f"game-publication-{publication_run}-1", "expired": False, "size_in_bytes": len(raw), "digest": "sha256:" + hashlib.sha256(raw).hexdigest(), "workflow_run": {"id": publication_run, "repository_id": 1442331254, "head_repository_id": 1442331254, "head_sha": REVISION, "head_branch": "main"}}]}

    def test_v2_auto_authority_requires_real_main_push_and_publication_chain_not_human_release_review(self):
        self.automatic_mode()
        self.api["/git/trees/" + REVISION]["tree"][0]["sha"] = "9" * 40
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "automatic_deployment_request_verified_no_execution")
        self.assertNotIn(TOKEN, result.stdout + result.stderr)

    def test_automatic_authority_rejects_broken_chain_and_unmerged_or_mismatched_sources(self):
        self.automatic_mode()
        original = json.dumps(self.api)
        request = dict(self.request)
        for case in ["manual-deploy", "manual-publisher", "failed-publisher", "fork", "PR-CI", "outsider-CI", "wrong-image", "old-image-source", "changed-workflow", "review-gate"]:
            with self.subTest(case=case):
                self.api = json.loads(original)
                self.request = dict(request)
                if case == "manual-deploy": self.api["/actions/runs/501"]["event"] = "workflow_dispatch"
                elif case == "manual-publisher": self.api["/actions/runs/503"]["event"] = "workflow_dispatch"
                elif case == "failed-publisher": self.api["/actions/runs/503"]["conclusion"] = "failure"
                elif case == "fork": self.api["/actions/runs/503"]["head_repository"]["id"] = 9
                elif case == "PR-CI": self.api["/actions/runs/502"]["event"] = "pull_request"
                elif case == "outsider-CI": self.api["/actions/runs/502"]["actor"]["id"] = 9
                elif case == "wrong-image": self.request["image_digest"] = "sha256:" + "9" * 64
                elif case == "old-image-source": self.request["image_source_revision"] = "9" * 40
                elif case == "changed-workflow": self.api["/contents/.github/workflows/game-deployment.yml?ref=" + REVISION]["sha"] = "9" * 40
                else: self.api["/environments/game-production"]["protection_rules"] = [{"type": "required_reviewers"}]
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Game deployment request blocked:", result.stderr)


if __name__ == "__main__":
    unittest.main()
