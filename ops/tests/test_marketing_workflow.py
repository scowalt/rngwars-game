import json
from pathlib import Path
import unittest
import yaml


ROOT = Path(__file__).resolve().parents[2]


class MarketingWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load((ROOT / ".github/workflows/marketing-artifact.yml").read_text())

    def test_source_build_has_no_signing_deployment_or_private_capability(self):
        workflow = self.workflow
        self.assertEqual(workflow["permissions"], {"contents": "read", "actions": "read"})
        self.assertEqual(workflow["jobs"]["build"]["permissions"], {"contents": "read"})
        self.assertNotIn("secrets.", json.dumps(workflow))
        for job in workflow["jobs"].values():
            self.assertEqual(job["runs-on"], "ubuntu-latest")
            self.assertNotIn("environment", job)
            self.assertLessEqual(job["timeout-minutes"], 15)
        self.assertEqual(workflow["jobs"]["build"]["env"]["PUBLIC_POSTHOG_KEY"], "")

    def test_signer_runs_only_trusted_code_after_independent_asset_validation(self):
        seal = self.workflow["jobs"]["seal"]
        self.assertEqual(seal["needs"], ["resolve", "build"])
        self.assertEqual(seal["permissions"], {"contents": "read", "actions": "read", "id-token": "write", "attestations": "write"})
        steps = seal["steps"]
        self.assertEqual(steps[0]["with"]["ref"], "${{ github.workflow_sha }}")
        self.assertFalse(steps[0]["with"]["persist-credentials"])
        assembly = next(i for i, step in enumerate(steps) if "marketing_producer.py seal" in step.get("run", ""))
        signing = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("actions/attest-build-provenance@"))
        verification = next(i for i, step in enumerate(steps) if "marketing_producer.py verify" in step.get("run", ""))
        upload = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("actions/upload-artifact@"))
        self.assertLess(assembly, signing)
        self.assertLess(signing, verification)
        self.assertLess(verification, upload)
        self.assertFalse(steps[signing]["with"]["push-to-registry"])
        self.assertFalse(steps[signing]["with"]["show-summary"])
        self.assertFalse(steps[upload]["with"]["overwrite"])
        self.assertNotIn("bun ", json.dumps(seal))
        for step in steps:
            if "uses" in step:
                self.assertRegex(step["uses"], r"@[a-f0-9]{40}$")
            self.assertNotIn("${{ inputs.", step.get("run", ""))
            self.assertNotIn("${{ github.event.", step.get("run", ""))

    def test_upstream_PR_and_fork_runs_cannot_enter_the_signing_graph(self):
        workflow = self.workflow
        self.assertEqual(set(workflow[True]), {"workflow_run", "workflow_dispatch"})
        self.assertEqual(workflow[True]["workflow_run"], {"workflows": ["CI"], "types": ["completed"]})
        gate = workflow["jobs"]["resolve"]["if"]
        for condition in ["github.repository_id == '1442331254'", "github.ref == 'refs/heads/main'", "github.run_attempt == 1", "github.event.workflow_run.conclusion == 'success'", "github.event.workflow_run.head_repository.full_name == github.repository", "github.event.workflow_run.event == 'push'", "github.event.workflow_run.event == 'workflow_dispatch'"]:
            self.assertIn(condition, gate)
        self.assertNotIn("pull_request", gate)
        self.assertFalse(workflow["concurrency"]["cancel-in-progress"])
        self.assertEqual(workflow["jobs"]["build"]["needs"], "resolve")


if __name__ == "__main__":
    unittest.main()
