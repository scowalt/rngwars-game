from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class GamePublicationWorkflowTests(unittest.TestCase):
    def test_native_source_build_is_separate_from_reviewed_registry_and_signing_permissions(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/game-publication.yml").read_text())
        triggers = workflow.get("on", workflow.get(True))
        self.assertEqual(set(triggers), {"workflow_dispatch"})
        self.assertEqual(triggers["workflow_dispatch"]["inputs"]["operation"]["default"], "validate")
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(workflow["env"]["GAME_PUBLICATION_ENABLED"], "${{ vars.GAME_PUBLICATION_ENABLED }}")
        self.assertNotIn("GAME_PUBLICATION_ENABLED", triggers["workflow_dispatch"]["inputs"])
        self.assertFalse(workflow["concurrency"]["cancel-in-progress"])
        jobs = workflow["jobs"]
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
        self.assertEqual(publish["if"], "inputs.operation == 'publish'")
        self.assertEqual(publish["permissions"], {"contents": "write", "actions": "read", "packages": "write", "attestations": "write", "id-token": "write"})
        signing = next(s for s in publish["steps"] if s.get("uses", "").startswith("actions/attest-build-provenance@"))
        self.assertEqual(signing["with"]["subject-name"], "ghcr.io/scowalt/rngwars-game-releases")
        self.assertTrue(signing["with"]["push-to-registry"])
        self.assertFalse(signing["with"]["create-storage-record"])
        self.assertTrue(any(s.get("if") == "always()" and "config.json" in s.get("run", "") for s in publish["steps"]))
        for job in jobs.values():
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(step["uses"], r"@[a-f0-9]{40}$")
                if step.get("uses", "").startswith("actions/checkout@"):
                    self.assertFalse(step["with"]["persist-credentials"])


if __name__ == "__main__":
    unittest.main()
