import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location("native_game_smoke", Path(__file__).parents[1] / "native_game_smoke.py")
n = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(n)


class NativeContextTests(unittest.TestCase):
    def test_rejects_local_x86_or_other_repository_execution(self):
        good = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY_ID": "1442331254", "RUNNER_ARCH": "ARM64", "GITHUB_SHA": "a" * 40}
        n.validate_context(good, "aarch64")
        for env, machine in [({}, "aarch64"), (good, "x86_64"), ({**good, "GITHUB_REPOSITORY_ID": "1"}, "aarch64"), ({**good, "GITHUB_SHA": "main"}, "aarch64")]:
            with self.subTest(machine=machine, env=env):
                with self.assertRaises(n.Failed):
                    n.validate_context(env, machine)


if __name__ == "__main__":
    unittest.main()
