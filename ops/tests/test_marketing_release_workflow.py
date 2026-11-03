import json
from pathlib import Path
import unittest
import yaml


ROOT = Path(__file__).resolve().parents[2]


class ReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load((ROOT / ".github/workflows/marketing-release.yml").read_text())

    def test_prepare_has_only_read_permissions_and_no_service_secrets(self):
        self.assertEqual(self.workflow["permissions"], {"contents": "read", "actions": "read", "attestations": "read"})
        prepare = self.workflow["jobs"]["prepare"]
        self.assertNotIn("secrets.", json.dumps(prepare))
        self.assertNotIn("environment", prepare)
        for text in ["github.repository_id == '1442331254'", "github.ref == 'refs/heads/main'", "github.run_attempt == 1"]:
            self.assertIn(text, prepare["if"])
        self.assertEqual(prepare["steps"][0]["with"]["ref"], "${{ github.workflow_sha }}")

    def test_release_requires_validated_candidate_enablement_and_protected_environment(self):
        release = self.workflow["jobs"]["release"]
        self.assertEqual(release["needs"], "prepare")
        self.assertIn("vars.MARKETING_RELEASE_ENABLED == 'true'", release["if"])
        self.assertEqual(release["environment"]["name"], "marketing-${{ needs.prepare.outputs.kind }}")
        self.assertEqual(release["permissions"], {"contents": "write", "actions": "read", "attestations": "read"})
        self.assertTrue(release["steps"][1]["with"]["no-cache"])
        self.assertNotIn("bun install", json.dumps(release))
        self.assertNotIn("id-token", release["permissions"])
        self.assertFalse(self.workflow["concurrency"]["cancel-in-progress"])
        secret_steps = [s for s in release["steps"] if "secrets." in json.dumps(s)]
        self.assertEqual(len(secret_steps), 1)
        self.assertEqual(secret_steps[0]["run"], "python3 scripts/marketing_release.py deploy")
        self.assertIn("EXPECTED_BUNDLE_SHA256", secret_steps[0]["env"])

    def test_dispatch_is_validation_only_by_default_and_no_fork_trigger_exists(self):
        self.assertEqual(set(self.workflow[True]), {"workflow_run", "workflow_dispatch"})
        self.assertEqual(self.workflow[True]["workflow_dispatch"]["inputs"]["operation"]["default"], "validate")
        self.assertNotIn("permissions", self.workflow["jobs"]["preflight"])
        self.assertEqual(self.workflow["jobs"]["preflight"]["environment"]["name"], "marketing-${{ needs.prepare.outputs.kind }}")
        self.assertEqual(self.workflow[True]["workflow_run"]["workflows"], ["Marketing artifact"])


if __name__ == "__main__":
    unittest.main()
