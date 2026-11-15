import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT / "ops/production/game-deployment/host-authority-pins.json"
PINNED_WORKFLOWS = {"workflow_blob": "game-deployment.yml", "ci_blob": "ci.yml"}


def git_blob(path):
    content = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


class HostAuthorityPinTests(unittest.TestCase):
    def test_privileged_workflows_match_the_host_authority_pins(self):
        pins = json.loads(PINS.read_text())
        self.assertEqual(set(pins), set(PINNED_WORKFLOWS))
        for field, filename in PINNED_WORKFLOWS.items():
            actual = git_blob(ROOT / ".github/workflows" / filename)
            self.assertEqual(
                pins[field],
                actual,
                f"{filename} changed, so the game host will refuse every automatic deploy with "
                f"request_controller_contract until its authority.json {field} is set to {actual}. "
                f"Review the change, update the host pin, then set {field} to {actual} in "
                f"{PINS.relative_to(ROOT)}. See docs/automatic-game-cd.md#host-policy-and-safe-waiting.",
            )


if __name__ == "__main__":
    unittest.main()
