import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class GamePublicationWorkflowTests(unittest.TestCase):
    def test_signer_and_registry_tools_share_only_a_new_private_Docker_home(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/game-publication.yml").read_text())
        steps = workflow["jobs"]["publish"]["steps"]
        setup = next(step for step in steps if step.get("id") == "credential-home")
        signing = next(step for step in steps if step.get("uses", "").startswith("actions/attest-build-provenance@"))
        cleanup = next(step for step in steps if step.get("name") == "Remove this job's registry authentication file")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            default = root / "default-home"
            (default / ".docker").mkdir(parents=True)
            existing = default / ".docker/config.json"
            existing.write_text('{"auths":{}}')
            environment = {"PATH": os.environ["PATH"], "HOME": str(default), "RUNNER_TEMP": str(root), "GITHUB_RUN_ID": "77", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_ENV": str(root / "github.env")}
            result = subprocess.run(["bash", "-eu", "-c", setup["run"]], env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            values = dict(line.split("=", 1) for line in (root / "github.env").read_text().splitlines())
            home = Path(values["GAME_PUBLICATION_HOME"])
            self.assertEqual(Path(values["DOCKER_CONFIG"]), home / ".docker")
            self.assertEqual(home.stat().st_mode & 0o777, 0o700)
            self.assertEqual(signing["env"]["HOME"], "${{ env.GAME_PUBLICATION_HOME }}")
            self.assertEqual(existing.read_text(), '{"auths":{}}')
            docker = home / ".docker"
            docker.mkdir(mode=0o700)
            (docker / "config.json").write_text(json.dumps({"auths": {"ghcr.io": {"auth": "synthetic-only"}}}))
            result = subprocess.run(["bash", "-eu", "-c", cleanup["run"]], env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(home.exists())
            self.assertEqual(existing.read_text(), '{"auths":{}}')

    def test_native_source_build_is_separate_from_reviewed_registry_and_signing_permissions(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/game-publication.yml").read_text())
        triggers = workflow.get("on", workflow.get(True))
        self.assertEqual(set(triggers), {"workflow_dispatch", "workflow_run"})
        self.assertEqual(triggers["workflow_run"], {"workflows": ["CI"], "types": ["completed"], "branches": ["main"]})
        self.assertEqual(triggers["workflow_dispatch"]["inputs"]["operation"]["options"], ["validate"])
        self.assertEqual(triggers["workflow_dispatch"]["inputs"]["operation"]["default"], "validate")
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(workflow["env"]["GAME_PUBLICATION_ENABLED"], "${{ vars.GAME_PUBLICATION_ENABLED }}")
        self.assertNotIn("GAME_PUBLICATION_ENABLED", triggers["workflow_dispatch"]["inputs"])
        self.assertFalse(workflow["concurrency"]["cancel-in-progress"])
        self.assertEqual(workflow["env"]["GAME_AUTOMATIC_CD_ENABLED"], "${{ vars.GAME_AUTOMATIC_CD_ENABLED }}")
        jobs = workflow["jobs"]
        for value in ["1442331254", "1100550", "refs/heads/main", "workflow_run.conclusion == 'success'", "workflow_run.head_repository.id", "workflow_run.event == 'push'", "GAME_AUTOMATIC_CD_ENABLED"]:
            self.assertIn(value, jobs["resolve"]["if"])
        native = jobs["native-build"]
        self.assertEqual(native["name"], "Build and exercise native image")
        self.assertEqual(native["runs-on"], "ubuntu-24.04-arm")
        self.assertEqual(native["permissions"], {"contents": "read"})
        self.assertNotIn("environment", native)
        self.assertNotIn("secrets.", str(native))
        builder = next(s for s in native["steps"] if s.get("uses", "").startswith("docker/build-push-action@"))
        self.assertFalse(builder["with"]["push"])
        self.assertFalse(builder["with"]["provenance"])
        self.assertEqual(builder["with"]["platforms"], "linux/arm64")
        self.assertEqual(builder["with"]["target"], "production")
        self.assertIn("type=oci", builder["with"]["outputs"])
        self.assertEqual(builder["env"], {"DOCKER_BUILD_SUMMARY": "false", "DOCKER_BUILD_RECORD_UPLOAD": "false"})
        self.assertEqual(jobs["prepare"]["permissions"], {"contents": "read", "actions": "read"})
        publish = jobs["publish"]
        self.assertEqual(publish["environment"], "game-publication")
        self.assertIn("github.event_name == 'workflow_run'", publish["if"])
        self.assertIn("needs.prepare.outputs.eligible == 'true'", publish["if"])
        self.assertEqual(publish["permissions"], {"contents": "write", "actions": "read", "packages": "write", "attestations": "write", "id-token": "write"})
        signing = next(s for s in publish["steps"] if s.get("uses", "").startswith("actions/attest-build-provenance@"))
        self.assertEqual(signing["with"]["subject-name"], "ghcr.io/scowalt/rngwars-game-releases")
        self.assertTrue(signing["with"]["push-to-registry"])
        self.assertFalse(signing["with"]["create-storage-record"])
        self.assertTrue(any(s.get("if") == "always()" and ".game-publication-home-owner" in s.get("run", "") for s in publish["steps"]))
        for job in jobs.values():
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(step["uses"], r"@[a-f0-9]{40}$")
                if step.get("uses", "").startswith("actions/checkout@"):
                    self.assertFalse(step["with"]["persist-credentials"])


if __name__ == "__main__":
    unittest.main()
