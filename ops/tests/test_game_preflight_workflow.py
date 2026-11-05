from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class PrivatePreflightWorkflowTests(unittest.TestCase):
    def test_only_the_reviewed_job_can_request_OIDC_or_receive_private_binding(self):
        text = (ROOT / ".github/workflows/game-deployment.yml").read_text()
        workflow = yaml.safe_load(text)
        triggers = workflow.get("on", workflow.get(True))
        self.assertEqual(set(triggers), {"workflow_dispatch"})
        inputs = triggers["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["operation"]["default"], "verify-release")
        self.assertEqual(inputs["operation"]["options"], ["verify-release", "private-preflight", "deploy"])
        self.assertNotIn("GAME_DEPLOYMENT_ENABLED", inputs)
        self.assertEqual(workflow["env"]["GAME_DEPLOYMENT_ENABLED"], "${{ vars.GAME_DEPLOYMENT_ENABLED }}")
        self.assertNotIn("GAME_PRIVATE_PREFLIGHT_ENABLED", inputs)
        self.assertEqual(workflow["env"]["GAME_PRIVATE_PREFLIGHT_ENABLED"], "${{ vars.GAME_PRIVATE_PREFLIGHT_ENABLED }}")
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertFalse(workflow["concurrency"]["cancel-in-progress"])
        jobs = workflow["jobs"]
        self.assertEqual(set(jobs), {"resolve", "preflight", "deploy"})
        deploy = jobs["deploy"]
        self.assertEqual(deploy["name"], "Deploy verified game release")
        self.assertEqual(deploy["if"], "inputs.operation == 'deploy'")
        self.assertEqual(deploy["environment"], "game-production")
        self.assertEqual(deploy["needs"], "resolve")
        self.assertEqual(deploy["permissions"], {"contents": "read", "actions": "read", "id-token": "write"})
        self.assertTrue(any("game_network.py deploy" in step.get("run", "") for step in deploy["steps"]))
        self.assertTrue(any(step.get("if") == "always()" and "game_network.py cleanup" in step.get("run", "") for step in deploy["steps"]))
        self.assertEqual(sum("secrets." in str(step) for step in deploy["steps"]), 1)
        self.assertIn("game-deployment-request-", str(jobs["resolve"]))
        self.assertIn("game_network.py request", str(jobs["resolve"]))
        resolve = jobs["resolve"]
        self.assertEqual(resolve["permissions"], {"contents": "read", "actions": "read"})
        self.assertNotIn("environment", resolve)
        self.assertNotIn("secrets.", str(resolve))
        self.assertIn("game_network.py resolve", str(resolve))
        self.assertIn("game_release.py fetch", str(resolve))
        private = jobs["preflight"]
        self.assertEqual(private["environment"], "game-production")
        self.assertEqual(private["needs"], "resolve")
        self.assertEqual(private["if"], "inputs.operation == 'private-preflight'")
        self.assertEqual(private["name"], "Private transport preflight")
        self.assertEqual(private["runs-on"], "ubuntu-24.04")
        self.assertEqual(private["permissions"], {"contents": "read", "actions": "read", "id-token": "write"})
        steps = private["steps"]
        probe = next(step for step in steps if "game_network.py probe" in step.get("run", ""))
        self.assertEqual(probe["env"]["GAME_NETWORK_BINDING"], "${{ secrets.GAME_NETWORK_BINDING }}")
        self.assertEqual(probe["env"]["GAME_SSH_PRIVATE_KEY"], "${{ secrets.GAME_SSH_PRIVATE_KEY }}")
        self.assertEqual(sum("secrets." in str(step) for step in steps), 1)
        self.assertTrue(any(step.get("if") == "always()" and "game_network.py cleanup" in step.get("run", "") for step in steps))
        installer = next(step for step in steps if "pkgs.tailscale.com" in step.get("run", ""))
        self.assertIn("1.104.1", installer["run"])
        self.assertIn("108d1d96ecf410d305571e173516f27038f870919a9b89c914a167c6d33a4528", installer["run"])
        self.assertIn("sha256sum --check --strict", installer["run"])
        self.assertNotIn("auth-key", installer["run"])
        self.assertNotIn("docker", text.lower())
        self.assertNotIn("init-db", text)
        for job in jobs.values():
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(step["uses"], r"@[a-f0-9]{40}$")
                if step.get("uses", "").startswith("actions/checkout@"):
                    self.assertEqual(step["with"]["ref"], "${{ github.sha }}")
                    self.assertFalse(step["with"]["persist-credentials"])
                if step.get("uses", "").startswith("actions/upload-artifact@"):
                    self.assertFalse(step["with"]["overwrite"])
                    self.assertNotIn("daemon.log", step["with"]["path"])


if __name__ == "__main__":
    unittest.main()
