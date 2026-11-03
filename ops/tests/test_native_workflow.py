import json
from pathlib import Path
import unittest
import yaml


ROOT = Path(__file__).resolve().parents[2]


class NativeWorkflowTests(unittest.TestCase):
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
        for step in job["steps"]:
            if "uses" in step:
                self.assertRegex(step["uses"], r"@[a-f0-9]{40}$")


if __name__ == "__main__":
    unittest.main()
