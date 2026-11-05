import json
from pathlib import Path
import unittest
import yaml


ROOT = Path(__file__).resolve().parents[2]


class NativeWorkflowTests(unittest.TestCase):
    def test_deployment_and_native_fixture_use_init_for_fatal_startup_exit(self):
        compose = yaml.safe_load((ROOT / "ops/production/docker-compose.yml").read_text())
        self.assertIs(compose["services"]["game"]["init"], True)
        source = (ROOT / "scripts/native_game_smoke.py").read_text()
        self.assertIn('"run", "-d", "--init"', source)
        self.assertIn('host["Init"] is True', source)
        self.assertNotIn("[DEBUG-", source)

    def test_native_image_validation_has_no_publication_or_private_capability(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/game-native.yml").read_text())
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        job = workflow["jobs"]["native-runtime"]
        self.assertEqual(job["runs-on"], "ubuntu-24.04-arm")
        self.assertNotIn("environment", job)
        self.assertNotIn("secrets.", json.dumps(workflow))
        builder = next(s for s in job["steps"] if s.get("uses", "").startswith("docker/build-push-action@"))
        self.assertFalse(builder["with"]["push"])
        self.assertTrue(builder["with"]["load"])
        self.assertEqual(builder["with"]["platforms"], "linux/arm64")
        self.assertEqual(builder["with"]["target"], "production")
        self.assertEqual(builder["env"], {"DOCKER_BUILD_SUMMARY": "false", "DOCKER_BUILD_RECORD_UPLOAD": "false"})
        upload = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/upload-artifact@"))
        self.assertEqual(upload["with"]["path"], "${{ runner.temp }}/native-game-result.json")
        self.assertFalse(upload["with"]["overwrite"])
        updater = next(s for s in job["steps"] if "native_updater_smoke.py" in s.get("run", ""))
        self.assertIn("RUNNER_ENVIRONMENT", updater["run"])
        self.assertIn("GITHUB_REPOSITORY_ID", updater["run"])
        self.assertTrue(any(s.get("with", {}).get("path") == "${{ runner.temp }}/native-updater-result.json" for s in job["steps"]))
        for step in job["steps"]:
            if "uses" in step:
                self.assertRegex(step["uses"], r"@[a-f0-9]{40}$")


if __name__ == "__main__":
    unittest.main()
