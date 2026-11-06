import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_game_artifact import fixture


TOOL = Path(__file__).parents[1] / "game_release.py"
REVISION = "a" * 40
DIGEST = "sha256:802be08bda929fdfd2e631512683bdec849c61f39fb7cfd47297554e11bb28b8"
IMAGE = "ghcr.io/scowalt/rngwars-game-releases"
REPOSITORY = "scowalt/rngwars-game"


class ReleaseVerificationCLITests(unittest.TestCase):
    def setUp(self):
        self.area = tempfile.TemporaryDirectory()
        self.addCleanup(self.area.cleanup)
        self.root = Path(self.area.name)
        self.digest = DIGEST
        files = fixture()
        manifest = files["blobs/sha256/" + DIGEST.split(":")[1]]
        configuration = json.loads(manifest)["config"]["digest"]
        (self.root / "manifest.json").write_bytes(manifest)
        (self.root / "config.json").write_bytes(files["blobs/sha256/" + configuration.split(":")[1]])
        (self.root / "bundle.jsonl").write_text('{"synthetic_bundle":true}\n')
        (self.root / "trusted-root.jsonl").write_text('{"synthetic_root":true}\n')
        self.statement = {"predicateType": "https://slsa.dev/provenance/v1", "subject": [{"name": IMAGE, "digest": {"sha256": DIGEST.split(":")[1]}}], "predicate": {"runDetails": {"metadata": {"invocationId": "https://github.com/scowalt/rngwars-game/actions/runs/77/attempts/1"}}}}
        self.run = {"id": 77, "repository": {"id": 1442331254}, "head_repository": {"id": 1442331254}, "head_sha": REVISION, "head_branch": "main", "path": ".github/workflows/game-publication.yml", "event": "workflow_dispatch", "run_attempt": 1, "status": "completed", "conclusion": "success", "actor": {"id": 1100550}, "triggering_actor": {"id": 1100550}}
        self.jobs = {"total_count": 4, "jobs": [{"name": name, "run_id": 77, "status": "completed", "conclusion": "success", "labels": ["ubuntu-24.04-arm" if name == "Build and exercise native image" else "ubuntu-24.04"]} for name in ["resolve", "Build and exercise native image", "prepare", "publish"]]}
        curl = self.root / "curl"
        curl.write_text("#!" + sys.executable + "\nimport json,os,sys\nfrom pathlib import Path\nroot=Path(__file__).parent\nassert not any(k in os.environ for k in ['GH_TOKEN','GITHUB_TOKEN','AWS_SECRET_ACCESS_KEY'])\nassert '-q' in sys.argv and '--location' not in sys.argv\nurl=sys.argv[-1]\nif url=='-':\n lines=sys.stdin.read().splitlines(); url=json.loads(next(line.split(' = ',1)[1] for line in lines if line.startswith('url = ')))\n if '/blobs/' in url and (root/'redirect').exists():\n  header=json.loads(next(line.split(' = ',1)[1] for line in lines if line.startswith('dump-header = ')))\n  Path(header).write_text('HTTP/1.1 307 Temporary Redirect\\r\\nLocation: '+(root/'redirect').read_text()+'\\r\\n\\r\\n')\n  sys.stdout.buffer.write(b'\\n307'); raise SystemExit(0)\n if url.startswith('https://pkg-containers.githubusercontent.com/'):\n  assert not any('Authorization:' in line for line in lines); body=(root/'config.json').read_bytes()\n elif url.startswith('https://ghcr.io/token?'):\n  assert 'push' not in url; body=b'{\"token\":\"synthetic-public-pull\"}'\n elif '/manifests/' in url: body=(root/'manifest.json').read_bytes()\n elif '/blobs/' in url: body=(root/'config.json').read_bytes()\n else: raise SystemExit(1)\n sys.stdout.buffer.write(body+b'\\n200'); raise SystemExit(0)\nif '/attestations/' in url:\n print(json.dumps({'attestations':[{'bundle':{'synthetic_bundle':True}}]})); raise SystemExit(0)\nif (root/'replace-manifest').exists(): (root/'manifest.json').write_bytes(b'changed after inspection')\nassert url.startswith('https://api.github.com/repos/scowalt/rngwars-game/actions/runs/77')\nname='jobs.json' if url.endswith('/attempts/1/jobs?per_page=100') else 'run.json'\nassert name=='jobs.json' or url.endswith('/runs/77')\nprint((root/name).read_text())\n")
        curl.chmod(0o700)
        gh = self.root / "gh"
        gh.write_text("#!" + sys.executable + "\nimport hashlib,json,os,sys\nfrom pathlib import Path\nroot=Path(__file__).parent\nargs=sys.argv[1:]\nif args==['attestation','trusted-root']:\n print((root/'trusted-root.jsonl').read_text()); raise SystemExit(0)\nassert args[:2]==['attestation','verify']\nassert not any(k in os.environ for k in ['GH_TOKEN','GITHUB_TOKEN','AWS_SECRET_ACCESS_KEY'])\nassert os.environ['HOME']!=str(root) and os.environ['GH_CONFIG_DIR']==os.environ['HOME']\nexpected={'--repo':'scowalt/rngwars-game','--cert-identity':'https://github.com/scowalt/rngwars-game/.github/workflows/game-publication.yml@refs/heads/main','--cert-oidc-issuer':'https://token.actions.githubusercontent.com','--signer-digest':'" + REVISION + "','--source-digest':'" + REVISION + "','--source-ref':'refs/heads/main','--predicate-type':'https://slsa.dev/provenance/v1'}\nassert all(args[args.index(k)+1]==v for k,v in expected.items())\nassert '--deny-self-hosted-runners' in args and '--bundle' in args and '--custom-trusted-root' in args\nassert hashlib.sha256(Path(args[2]).read_bytes()).hexdigest()==json.loads((root/'statement.json').read_text())['subject'][0]['digest']['sha256']\nprint(json.dumps([{'verificationResult':{'statement':json.loads((root/'statement.json').read_text())}}]))\n")
        gh.chmod(0o700)
        self.environment = {"PATH": str(self.root) + os.pathsep + os.environ["PATH"], "HOME": str(self.root), "GH_TOKEN": "synthetic-owner-token", "GITHUB_TOKEN": "synthetic-actions-token", "AWS_SECRET_ACCESS_KEY": "synthetic-backup-key"}

    def invoke(self, operation="verify"):
        for name, value in [("run", self.run), ("jobs", self.jobs), ("statement", self.statement)]:
            (self.root / (name + ".json")).write_text(json.dumps(value))
        inputs = ["verify", str(self.root / "manifest.json"), str(self.root / "config.json"), str(self.root / "bundle.jsonl"), "--trusted-root", str(self.root / "trusted-root.jsonl")] if operation == "verify" else ["fetch", str(self.root / "fetched")]
        return subprocess.run([sys.executable, str(TOOL), *inputs, "--revision", REVISION, "--digest", self.digest, "--publication-run", "77"], env=self.environment, capture_output=True, text=True, timeout=15)

    def test_verifies_exact_image_and_successful_publisher_without_credentials_or_deployment(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "release_verified_not_deployment_approval")
        self.assertEqual(value["image"], IMAGE + "@" + DIGEST)
        self.assertEqual(value["publication_run_id"], 77)
        self.assertNotIn("synthetic-owner-token", result.stdout + result.stderr)

    def test_rejects_partial_publication_even_when_its_signature_is_valid(self):
        self.run["conclusion"] = "failure"
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release_publication_not_successful", result.stderr)

    def test_requires_the_same_owner_main_source_workflow_and_first_publication_attempt(self):
        original = json.dumps(self.run)
        changes = [{"id": 78}, {"repository": {"id": 7}}, {"head_repository": {"id": 7}}, {"head_sha": "b" * 40}, {"head_branch": "other"}, {"path": ".github/workflows/other.yml"}, {"actor": {"id": 7}}, {"triggering_actor": {"id": 7}}, {"event": "pull_request"}, {"run_attempt": 2}, {"run_attempt": True}]
        for change in changes:
            with self.subTest(change=change):
                self.run = {**json.loads(original), **change}
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("release_publication_identity", result.stderr)

    def test_requires_complete_successful_native_and_publish_jobs(self):
        original = json.dumps(self.jobs)
        for case in ["skipped-publish", "wrong-native-runner", "different-run", "duplicate", "truncated"]:
            with self.subTest(case=case):
                self.jobs = json.loads(original)
                if case == "skipped-publish":
                    self.jobs["jobs"][-1]["conclusion"] = "skipped"
                elif case == "wrong-native-runner":
                    self.jobs["jobs"][1]["labels"] = ["ubuntu-24.04"]
                elif case == "different-run":
                    self.jobs["jobs"][1]["run_id"] = 78
                elif case == "duplicate":
                    self.jobs["jobs"][-1]["name"] = "prepare"
                else:
                    self.jobs["total_count"] = 5
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("release_publication_jobs", result.stderr)

    def test_rejects_digest_bound_images_with_wrong_runtime_or_revision(self):
        for files in [fixture(architecture="amd64"), fixture(user="0:0"), fixture(revision="b" * 40)]:
            with self.subTest(image=list(files)):
                self.digest = json.loads(files["index.json"])["manifests"][0]["digest"]
                manifest = files["blobs/sha256/" + self.digest.split(":")[1]]
                configuration = json.loads(manifest)["config"]["digest"]
                (self.root / "manifest.json").write_bytes(manifest)
                (self.root / "config.json").write_bytes(files["blobs/sha256/" + configuration.split(":")[1]])
                self.statement["subject"][0]["digest"]["sha256"] = self.digest.split(":")[1]
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("release_runtime_identity", result.stderr)

    def test_verifies_the_inspected_snapshot_even_if_input_changes_during_provider_reads(self):
        (self.root / "replace-manifest").touch()
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["image"], IMAGE + "@" + DIGEST)
        self.assertEqual((self.root / "manifest.json").read_bytes(), b"changed after inspection")

    def test_rejects_non_OCI_or_external_descriptors_even_with_a_matching_manifest_digest(self):
        original = (self.root / "manifest.json").read_bytes()
        for case in ["schema", "media", "external-config", "external-layer", "empty-layers", "negative-size"]:
            with self.subTest(case=case):
                manifest = json.loads(original)
                if case == "schema":
                    manifest["schemaVersion"] = 1
                elif case == "media":
                    manifest["mediaType"] = "application/vnd.oci.image.index.v1+json"
                elif case == "external-config":
                    manifest["config"]["urls"] = ["https://untrusted.invalid/config"]
                elif case == "external-layer":
                    manifest["layers"][0]["urls"] = ["https://untrusted.invalid/layer"]
                elif case == "empty-layers":
                    manifest["layers"] = []
                else:
                    manifest["layers"][0]["size"] = -1
                content = json.dumps(manifest).encode()
                (self.root / "manifest.json").write_bytes(content)
                self.digest = "sha256:" + hashlib.sha256(content).hexdigest()
                self.statement["subject"][0]["digest"]["sha256"] = self.digest.split(":")[1]
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("release_manifest_shape", result.stderr)

    def test_rejects_config_rootfs_that_does_not_bind_every_layer(self):
        config = json.loads((self.root / "config.json").read_bytes())
        config["rootfs"]["diff_ids"] = []
        content = json.dumps(config).encode()
        (self.root / "config.json").write_bytes(content)
        manifest = json.loads((self.root / "manifest.json").read_bytes())
        manifest["config"].update(digest="sha256:" + hashlib.sha256(content).hexdigest(), size=len(content))
        content = json.dumps(manifest).encode()
        (self.root / "manifest.json").write_bytes(content)
        self.digest = "sha256:" + hashlib.sha256(content).hexdigest()
        self.statement["subject"][0]["digest"]["sha256"] = self.digest.split(":")[1]
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release_rootfs_binding", result.stderr)

    def test_rejects_signatures_for_another_image_or_invocation(self):
        original = json.dumps(self.statement)
        for case in ["name", "invocation", "predicate"]:
            with self.subTest(case=case):
                self.statement = json.loads(original)
                if case == "name":
                    self.statement["subject"][0]["name"] = "ghcr.io/other/image"
                elif case == "invocation":
                    self.statement["predicate"]["runDetails"]["metadata"]["invocationId"] = "https://github.com/scowalt/rngwars-game/actions/runs/78/attempts/1"
                else:
                    self.statement["predicateType"] = "https://untrusted.invalid/predicate"
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("release_attestation_binding", result.stderr)

    def test_verifier_failure_is_fail_closed_without_leaking_its_diagnostics(self):
        executable = self.root / "gh"
        executable.write_text("#!" + sys.executable + "\nimport sys\nprint('synthetic-sensitive-provider-value',file=sys.stderr)\nraise SystemExit(1)\n")
        executable.chmod(0o700)
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release_verification_tool_failed", result.stderr)
        self.assertNotIn("synthetic-sensitive-provider-value", result.stdout + result.stderr)

    def test_refuses_symlink_hardlink_and_oversized_or_empty_evidence(self):
        bundle = self.root / "bundle.jsonl"
        for case in ["symlink", "hardlink", "oversized", "empty"]:
            with self.subTest(case=case):
                bundle.unlink()
                if case == "symlink":
                    bundle.symlink_to(self.root / "trusted-root.jsonl")
                elif case == "hardlink":
                    os.link(self.root / "trusted-root.jsonl", bundle)
                else:
                    bundle.write_bytes(b"x" * (2 * 1024 * 1024 + 1) if case == "oversized" else b"")
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("release_file_", result.stderr)

    def test_refuses_tampered_manifest_and_config_bytes(self):
        for name, code in [("manifest.json", "release_manifest_digest"), ("config.json", "release_config_digest")]:
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(code, result.stderr)
                path.write_bytes(original)

    def test_fetches_and_verifies_public_evidence_without_overwriting_an_existing_output(self):
        result = self.invoke("fetch")
        self.assertEqual(result.returncode, 0, result.stderr)
        destination = self.root / "fetched"
        self.assertEqual({p.name for p in destination.iterdir()}, {"manifest.json", "config.json", "bundle.jsonl", "trusted-root.jsonl"})
        self.assertEqual((destination / "manifest.json").read_bytes(), (self.root / "manifest.json").read_bytes())
        self.assertEqual(json.loads(result.stdout)["status"], "release_verified_not_deployment_approval")
        result = self.invoke("fetch")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release_destination_exists", result.stderr)
        self.assertEqual((destination / "config.json").read_bytes(), (self.root / "config.json").read_bytes())

    def test_drops_registry_authorization_on_the_allowlisted_config_CDN_redirect(self):
        (self.root / "redirect").write_text("https://pkg-containers.githubusercontent.com/fixture?sig=synthetic")
        result = self.invoke("fetch")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("synthetic-public-pull", result.stdout + result.stderr)

    def test_rejects_registry_redirects_outside_the_expected_https_CDN(self):
        for destination in ["https://untrusted.invalid/blob", "http://pkg-containers.githubusercontent.com/blob", "https://pkg-containers.githubusercontent.com:444/blob", "https://name:password@pkg-containers.githubusercontent.com/blob"]:
            with self.subTest(destination=destination):
                (self.root / "redirect").write_text(destination)
                result = self.invoke("fetch")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("release_registry_", result.stderr)
                self.assertFalse((self.root / "fetched").exists())

    def test_verifies_an_automatic_publisher_with_the_same_genuine_source_and_invocation(self):
        self.run["event"] = "workflow_run"
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["publication_run_id"], 77)


if __name__ == "__main__":
    unittest.main()
