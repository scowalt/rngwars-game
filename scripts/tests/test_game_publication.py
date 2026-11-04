import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from test_game_artifact import archive, fixture


TOOL = Path(__file__).parents[1] / "game_publication.py"
REVISION = "a" * 40
REPOSITORY = "scowalt/rngwars-game"
WORKFLOW = REPOSITORY + "/.github/workflows/game-publication.yml@refs/heads/main"


class PublicationCLITests(unittest.TestCase):
    def setUp(self):
        self.area = tempfile.TemporaryDirectory()
        self.addCleanup(self.area.cleanup)
        self.root = Path(self.area.name)
        gh = self.root / "gh"
        gh.write_text("#!" + sys.executable + "\nimport json,os,sys\nfrom pathlib import Path\nargs=sys.argv[1:]\nif args[0]=='attestation':\n expected={'--cert-identity':'https://github.com/scowalt/rngwars-game/.github/workflows/game-publication.yml@refs/heads/main','--signer-digest':'" + REVISION + "','--source-digest':'" + REVISION + "','--source-ref':'refs/heads/main','--cert-oidc-issuer':'https://token.actions.githubusercontent.com','--predicate-type':'https://slsa.dev/provenance/v1'}\n assert args[1]=='verify' and '--deny-self-hosted-runners' in args and '--bundle-from-oci' in args\n assert all(args[args.index(k)+1]==v for k,v in expected.items())\n print(Path(os.environ['HOME'],'attestations.json').read_text()); raise SystemExit(0)\nassert args[0]=='api'\nmethod=args[args.index('--method')+1]\nroute=args[-1].removeprefix('repos/scowalt/rngwars-game')\nif method=='POST':\n body=json.load(sys.stdin)\n with Path(os.environ['HOME'],'writes.jsonl').open('a') as f: f.write(json.dumps({'route':route,'body':body})+'\\n')\nelse: assert method=='GET'\nif route=='/actions/artifacts/99/zip':\n sys.stdout.buffer.write(Path(os.environ['HOME'],'artifact.zip').read_bytes()); raise SystemExit(0)\nresponses=json.loads(Path(os.environ['HOME'],'responses.json').read_text())\nif route not in responses: raise SystemExit(1)\nif '__http_error' in responses[route]:\n sys.stderr.write('gh: unexpected-sensitive-provider-message (HTTP '+str(responses[route]['__http_error'])+')'); raise SystemExit(1)\nprint(json.dumps(responses[route]))\n")
        gh.chmod(0o700)
        self.env = {"PATH": str(self.root) + os.pathsep + os.environ["PATH"], "HOME": str(self.root), "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_REPOSITORY_ID": "1442331254", "GITHUB_REPOSITORY_OWNER_ID": "1100550", "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": REVISION, "GITHUB_WORKFLOW_SHA": REVISION, "GITHUB_WORKFLOW_REF": WORKFLOW, "GITHUB_RUN_ID": "77", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_ACTOR": "scowalt", "GITHUB_ACTOR_ID": "1100550", "GITHUB_TRIGGERING_ACTOR": "scowalt", "SOURCE_CI_RUN_ID": "42", "APPROVED_REVISION": REVISION}
        identity = {"id": 1442331254}
        self.responses = {"": {**identity, "private": False, "default_branch": "main"}, "/git/ref/heads/main": {"object": {"sha": REVISION}}, "/actions/workflows/ci.yml": {"id": 11, "state": "active", "path": ".github/workflows/ci.yml"}, "/actions/runs/42": {"id": 42, "repository": identity, "head_repository": identity, "event": "push", "run_attempt": 1, "status": "completed", "conclusion": "success", "workflow_id": 11, "path": ".github/workflows/ci.yml", "head_sha": REVISION, "head_branch": "main"}, "/contents/.github/workflows/ci.yml?ref=" + REVISION: {"type": "file", "sha": "b" * 40}, "/actions/runs/42/attempts/1/jobs?per_page=100": {"total_count": 3, "jobs": [{"name": name, "status": "completed", "conclusion": "success"} for name in ["Build API (F#)", "Build Frontend (SolidJS)", "Portable SQLite backup and deployment preparation"]]}, "/actions/workflows/game-publication.yml": {"id": 12, "path": ".github/workflows/game-publication.yml", "state": "active"}, "/actions/runs/77": {"id": 77, "workflow_id": 12, "path": ".github/workflows/game-publication.yml", "head_sha": REVISION, "head_branch": "main", "repository": identity, "head_repository": identity, "event": "workflow_dispatch", "run_attempt": 1, "status": "in_progress", "actor": {"id": 1100550}, "triggering_actor": {"id": 1100550}}}

        self.responses["/actions/runs/42"]["created_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def invoke(self, *args):
        (self.root / "responses.json").write_text(json.dumps(self.responses))
        return subprocess.run([sys.executable, str(TOOL), *args], env=self.env, capture_output=True, text=True, timeout=15)

    def native_artifact(self):
        files = fixture()
        index = json.loads(files["index.json"])
        manifest = json.loads(files["blobs/sha256/" + index["manifests"][0]["digest"].split(":")[1]])
        native = {"source_revision": REVISION, "image_id": manifest["config"]["digest"], "native_runner_architecture": "aarch64", "image_architecture": "arm64", "container_init": True, "checks": ["production_rejects_unmarked_empty_population", "offline_initialization_without_web_host", "offline_initialization_rejects_root", "encrypted_empty_baseline_backup_restore", "production_accepts_initialized_empty_restore", "native_SQLite_signup", "profile_update", "practice_creation", "production_restart_with_same_DB_and_token", "bundled_frontend", "distributed_legal_notices", "production_does_not_create_missing_DB"], "synthetic_data_only": True, "published_host_ports": False, "external_container_network": False, "production_host_access": False}
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as transport:
            transport.writestr("image.oci.tar", archive(files))
            transport.writestr("native-game-result.json", json.dumps(native))
        raw = content.getvalue()
        (self.root / "artifact.zip").write_bytes(raw)
        self.responses["/actions/artifacts/99"] = {"id": 99, "name": "game-image-77-1", "expired": False, "size_in_bytes": len(raw), "digest": "sha256:" + hashlib.sha256(raw).hexdigest(), "workflow_run": {"id": 77, "repository_id": 1442331254, "head_repository_id": 1442331254, "head_sha": REVISION, "head_branch": "main"}}
        self.responses["/actions/runs/77/attempts/1/jobs?per_page=100"] = {"total_count": 1, "jobs": [{"id": 101, "name": "Build and exercise native image", "run_id": 77, "status": "completed", "conclusion": "success", "labels": ["ubuntu-24.04-arm"]}]}

    def test_prepares_the_bound_native_artifact_without_overwriting_output(self):
        self.native_artifact()
        destination = self.root / "accepted"
        result = self.invoke("prepare", str(destination), "--artifact-id", "99")
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "native_candidate_verified_no_publication")
        self.assertEqual(value["image_digest"], "sha256:802be08bda929fdfd2e631512683bdec849c61f39fb7cfd47297554e11bb28b8")
        self.assertEqual((destination / "image.oci.tar").read_bytes(), archive(fixture()))
        before = sorted(path.name for path in destination.iterdir())
        result = self.invoke("prepare", str(destination), "--artifact-id", "99")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, sorted(path.name for path in destination.iterdir()))

    def publication_capability(self):
        self.native_artifact()
        files = fixture()
        manifest = files["blobs/sha256/" + json.loads(files["index.json"])["manifests"][0]["digest"].split(":")[1]]
        config = files["blobs/sha256/" + json.loads(manifest)["config"]["digest"].split(":")[1]]
        (self.root / "registry-manifest").write_bytes(manifest)
        (self.root / "registry-config").write_bytes(config)
        curl = self.root / "curl"
        curl.write_text("#!" + sys.executable + "\nimport json,os,sys\nfrom pathlib import Path\nroot=Path(os.environ['HOME']); lines=sys.stdin.read().splitlines(); url=json.loads(next(s.split(' = ',1)[1] for s in lines if s.startswith('url = ')))\nif url.startswith('https://ghcr.io/token?'): data=b'{\\\"token\\\":\\\"synthetic-registry-session\\\"}'; status=200\nelif '/manifests/' in url:\n data=(root/'registry-manifest').read_bytes() if (root/'pushed').exists() else b'{}'; status=200 if (root/'pushed').exists() else 404\nelif '/blobs/' in url: data=(root/'registry-config').read_bytes(); status=200\nelse: raise SystemExit(1)\nsys.stdout.buffer.write(data+b'\\n'+str(status).encode())\n")
        curl.chmod(0o700)
        skopeo = self.root / "skopeo"
        skopeo.write_text("#!" + sys.executable + "\nimport os,sys\nfrom pathlib import Path\nassert 'copy' in sys.argv and '--preserve-digests' in sys.argv\nassert sys.argv[-1]=='docker://ghcr.io/scowalt/rngwars-game-releases:" + REVISION + "'\nassert Path(os.environ['REGISTRY_AUTH_FILE']).is_file()\nPath(os.environ['HOME'],'pushed').write_text('published')\n")
        skopeo.chmod(0o700)
        self.env.update(GH_TOKEN="synthetic-github-package-token", DOCKER_CONFIG=str(self.root / "registry-auth"), GAME_PUBLICATION_OPERATION="publish", EXPECTED_IMAGE_DIGEST="sha256:802be08bda929fdfd2e631512683bdec849c61f39fb7cfd47297554e11bb28b8")
        self.env["EXPECTED_ARCHIVE_SHA256"] = hashlib.sha256(archive(files)).hexdigest()
        self.env["GAME_PUBLICATION_ENABLED"] = "true"
        attempt = "release-attempt/game-publication/" + REVISION
        self.responses.update({"/environments/game-publication": {"id": 400, "name": "game-publication", "can_admins_bypass": False, "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}, "protection_rules": [{"type": "required_reviewers", "prevent_self_review": False, "reviewers": [{"type": "User", "reviewer": {"id": 1100550}}]}]}, "/environments/game-publication/deployment-branch-policies": {"total_count": 1, "branch_policies": [{"name": "main", "type": "branch"}]}, "/actions/runs/77/approvals": [{"state": "approved", "user": {"id": 1100550}, "environments": [{"id": 400, "name": "game-publication"}]}], "/rulesets?per_page=100": [{"id": 50, "name": "Immutable release attempts", "target": "tag", "enforcement": "active"}], "/rulesets/50": {"conditions": {"ref_name": {"include": ["refs/tags/release-attempt/**"], "exclude": []}}, "rules": [{"type": "update"}, {"type": "deletion"}], "bypass_actors": []}, "/git/matching-refs/tags/" + attempt: [], "/git/tags": {"sha": "c" * 40}, "/git/refs": {"ref": "refs/tags/" + attempt, "object": {"sha": "c" * 40}}})
        return attempt

    def test_publishes_only_after_actual_environment_review_and_immutable_reservation(self):
        attempt = self.publication_capability()
        result = self.invoke("publish", str(self.root / "publish-candidate"), "--artifact-id", "99")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "image_published_not_yet_attested")
        self.assertTrue((self.root / "pushed").exists())
        writes = [json.loads(line) for line in (self.root / "writes.jsonl").read_text().splitlines()]
        self.assertEqual(writes[-1]["body"]["ref"], "refs/tags/" + attempt)
        self.assertNotIn("synthetic-github-package-token", result.stdout + result.stderr)

    def test_uses_real_verifier_protocol_and_requires_this_publication_invocation(self):
        self.publication_capability()
        result = self.invoke("publish", str(self.root / "candidate"), "--artifact-id", "99")
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = self.root / "published.json"
        receipt.write_text(result.stdout)
        statement = {"predicateType": "https://slsa.dev/provenance/v1", "subject": [{"digest": {"sha256": "802be08bda929fdfd2e631512683bdec849c61f39fb7cfd47297554e11bb28b8"}}], "predicate": {"runDetails": {"metadata": {"invocationId": "https://github.com/scowalt/rngwars-game/actions/runs/77/attempts/1"}}}}
        attestation = self.root / "attestations.json"
        attestation.write_text(json.dumps([{"verificationResult": {"statement": statement}}]))
        result = self.invoke("verify-published", str(receipt))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "game_image_publication_verified")
        statement["predicate"]["runDetails"]["metadata"]["invocationId"] = "https://github.com/scowalt/rngwars-game/actions/runs/76/attempts/1"
        attestation.write_text(json.dumps([{"verificationResult": {"statement": statement}}]))
        result = self.invoke("verify-published", str(receipt))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("game_attestation_invocation", result.stderr)

    def test_uses_GitHub_injected_enablement_without_variable_management_access(self):
        self.publication_capability()
        self.env["GAME_PUBLICATION_ENABLED"] = "true"
        self.assertNotIn("/actions/variables/GAME_PUBLICATION_ENABLED", self.responses)
        result = self.invoke("resolve")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "game_source_resolved_no_publication")
        self.assertFalse((self.root / "writes.jsonl").exists())

    def test_metadata_denial_reports_only_safe_endpoint_class_and_status(self):
        self.publication_capability()
        self.responses["/environments/game-publication"] = {"__http_error": 403}
        result = self.invoke("resolve")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("github_game_environment_http_403", result.stderr)
        self.assertNotIn("unexpected-sensitive-provider-message", result.stdout + result.stderr)

    def test_publication_resolution_requires_preexisting_protected_environment(self):
        self.publication_capability()
        self.responses["/environments/game-publication"]["can_admins_bypass"] = True
        result = self.invoke("resolve")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("game_publication_environment", result.stderr)
        self.assertFalse((self.root / "writes.jsonl").exists())

    def test_refuses_unreviewed_or_unsafe_environment_without_registry_or_attempt_writes(self):
        for case in ["disabled", "bypass", "wildcard", "unreviewed", "other-reviewer", "changed-digest", "reserved"]:
            with self.subTest(case=case):
                attempt = self.publication_capability()
                self.env["DOCKER_CONFIG"] = str(self.root / ("auth-" + case))
                if case == "disabled":
                    self.env["GAME_PUBLICATION_ENABLED"] = "false"
                elif case == "bypass":
                    self.responses["/environments/game-publication"]["can_admins_bypass"] = True
                elif case == "wildcard":
                    self.responses["/environments/game-publication/deployment-branch-policies"]["branch_policies"][0]["name"] = "*"
                elif case == "unreviewed":
                    self.responses["/actions/runs/77/approvals"] = []
                elif case == "other-reviewer":
                    self.responses["/actions/runs/77/approvals"][0]["user"]["id"] = 7
                elif case == "changed-digest":
                    self.env["EXPECTED_IMAGE_DIGEST"] = "sha256:" + "0" * 64
                else:
                    self.responses["/git/matching-refs/tags/" + attempt] = [{"ref": "refs/tags/" + attempt}]
                result = self.invoke("publish", str(self.root / ("candidate-" + case)), "--artifact-id", "99")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "writes.jsonl").exists())
                self.assertFalse((self.root / "pushed").exists())
                self.assertNotIn("synthetic-github-package-token", result.stdout + result.stderr)

    def test_ambiguous_registry_failure_preserves_the_attempt_without_retry(self):
        attempt = self.publication_capability()
        skopeo = self.root / "skopeo"
        skopeo.write_text("#!" + sys.executable + "\nimport os\nfrom pathlib import Path\nroot=Path(os.environ['HOME'])\nwith (root/'push-count').open('a') as f: f.write('attempt\\n')\n(root/'pushed').write_text('possibly-published')\nraise SystemExit(1)\n")
        skopeo.chmod(0o700)
        result = self.invoke("publish", str(self.root / "candidate"), "--artifact-id", "99")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("game_registry_push_failed_no_retry", result.stderr)
        self.assertEqual((self.root / "push-count").read_text(), "attempt\n")
        writes = [json.loads(line) for line in (self.root / "writes.jsonl").read_text().splitlines()]
        self.assertEqual(writes[-1]["body"]["ref"], "refs/tags/" + attempt)
        self.assertEqual((self.root / "pushed").read_text(), "possibly-published")

    def test_changed_archive_approval_is_rejected_before_any_mutation(self):
        self.publication_capability()
        self.env["EXPECTED_ARCHIVE_SHA256"] = "0" * 64
        result = self.invoke("publish", str(self.root / "candidate"), "--artifact-id", "99")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("game_publication_not_approved", result.stderr)
        self.assertFalse((self.root / "writes.jsonl").exists())
        self.assertFalse((self.root / "pushed").exists())

    def test_existing_registry_tag_is_not_overwritten_or_reserved_again(self):
        self.publication_capability()
        (self.root / "pushed").write_text("existing-image")
        result = self.invoke("publish", str(self.root / "candidate"), "--artifact-id", "99")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("game_registry_tag_not_absent_200", result.stderr)
        self.assertFalse((self.root / "writes.jsonl").exists())
        self.assertEqual((self.root / "pushed").read_text(), "existing-image")

    def test_rejects_wrong_artifact_identity_native_job_and_transport(self):
        for case in ["other-run", "other-revision", "failed-native", "wrong-runner", "changed-download"]:
            with self.subTest(case=case):
                self.native_artifact()
                artifact = self.responses["/actions/artifacts/99"]
                job = self.responses["/actions/runs/77/attempts/1/jobs?per_page=100"]["jobs"][0]
                if case == "other-run":
                    artifact["workflow_run"]["id"] = 76
                elif case == "other-revision":
                    artifact["workflow_run"]["head_sha"] = "b" * 40
                elif case == "failed-native":
                    job["conclusion"] = "failure"
                elif case == "wrong-runner":
                    job["labels"] = ["ubuntu-latest"]
                else:
                    (self.root / "artifact.zip").write_bytes(b"unexpected-sensitive-payload")
                destination = self.root / ("rejected-" + case)
                result = self.invoke("prepare", str(destination), "--artifact-id", "99")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(destination.exists())
                self.assertNotIn("unexpected-sensitive-payload", result.stdout + result.stderr)

    def test_refuses_forks_other_actors_reruns_and_mismatched_revision(self):
        original = dict(self.env)
        cases = [{"GITHUB_EVENT_NAME": "pull_request"}, {"GITHUB_REF": "refs/heads/feature"}, {"GITHUB_RUN_ATTEMPT": "2"}, {"GITHUB_ACTOR_ID": "7"}, {"GITHUB_TRIGGERING_ACTOR": "someone-else"}, {"GITHUB_REPOSITORY_ID": "1"}, {"APPROVED_REVISION": "b" * 40}, {"GITHUB_WORKFLOW_SHA": "b" * 40}]
        for change in cases:
            with self.subTest(change=change):
                self.env = {**original, **change}
                result = self.invoke("resolve")
                self.assertNotEqual(result.returncode, 0)
        self.env = original

    def test_refuses_failed_or_incomplete_provider_CI_results(self):
        jobs = self.responses["/actions/runs/42/attempts/1/jobs?per_page=100"]
        jobs["jobs"][0]["conclusion"] = "failure"
        self.assertNotEqual(self.invoke("resolve").returncode, 0)
        jobs["jobs"][0]["conclusion"] = "success"
        jobs["jobs"].pop()
        self.assertNotEqual(self.invoke("resolve").returncode, 0)

    def test_rejects_stale_CI_even_when_its_revision_is_still_main(self):
        self.responses["/actions/runs/42"]["created_at"] = "2020-01-01T00:00:00Z"
        result = self.invoke("resolve")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("game_CI_freshness", result.stderr)

    def test_resolves_only_actual_successful_main_CI_before_any_publication(self):
        result = self.invoke("resolve")
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "game_source_resolved_no_publication")
        self.assertEqual(value["source_revision"], REVISION)
        self.assertEqual(value["ci_run_id"], 42)
        self.assertEqual(value["publication_run_id"], 77)


if __name__ == "__main__":
    unittest.main()
