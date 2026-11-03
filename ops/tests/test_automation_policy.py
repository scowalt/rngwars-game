import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class AutomationPolicyTests(unittest.TestCase):
    def test_dependency_pause_and_review_requirements_are_preserved(self):
        config = json.loads((ROOT / "renovate.json").read_text())
        self.assertIs(config["enabled"], False)
        self.assertIs(config["automerge"], False)
        self.assertIs(config["platformAutomerge"], False)
        self.assertEqual(config["prHourlyLimit"], 2)
        self.assertEqual(config["prConcurrentLimit"], 3)
        self.assertIs(config["lockFileMaintenance"]["automerge"], False)
        for rule in config["packageRules"]:
            self.assertIsNot(rule.get("automerge"), True)
            if "major" in rule.get("matchUpdateTypes", []):
                self.assertIs(rule["dependencyDashboardApproval"], True)


if __name__ == "__main__":
    unittest.main()
