import json
import os
import pty
from pathlib import Path
import subprocess
import sys
import unittest


TOOL = Path(__file__).parents[1] / "game_ssh_probe.py"


class RestrictedSSHProbeTests(unittest.TestCase):
    def invoke(self, request, command="rngwars-game-preflight-v1", args=()):
        environment = {"PATH": os.defpath, "SSH_ORIGINAL_COMMAND": command, "SYNTHETIC_SECRET": "must-not-appear"}
        return subprocess.run([sys.executable, str(TOOL), *args], input=request, env=environment, capture_output=True, text=True, timeout=10)

    def test_echoes_only_a_valid_transport_challenge_without_claiming_deployment(self):
        result = self.invoke(json.dumps({"version": 1, "challenge": "a" * 64}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"version": 1, "challenge": "a" * 64, "status": "restricted_transport_only"})
        self.assertNotIn("must-not-appear", result.stdout + result.stderr)

    def test_rejects_interactive_shell_arbitrary_commands_subsystems_and_extra_arguments(self):
        request = json.dumps({"version": 1, "challenge": "a" * 64})
        for command in ["", "sh", "echo must-not-appear", "sftp", "rngwars-game-preflight-v1; sh"]:
            with self.subTest(command=command):
                result = self.invoke(request, command=command)
                self.assertEqual(result.returncode, 64)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("must-not-appear", result.stderr)
        self.assertEqual(self.invoke(request, args=("--policy", "/untrusted")).returncode, 64)

    def test_rejects_unknown_fields_invalid_versions_and_unbounded_challenges(self):
        good = {"version": 1, "challenge": "a" * 64}
        invalid = [{**good, "version": True}, {**good, "version": 2}, {**good, "command": "must-not-appear"}, {**good, "challenge": "must-not-appear"}, {**good, "challenge": "A" * 64}, {**good, "challenge": "a" * 65}, [good]]
        for value in invalid:
            with self.subTest(value=type(value).__name__):
                result = self.invoke(json.dumps(value))
                self.assertEqual(result.returncode, 64)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("must-not-appear", result.stderr)

    def test_rejects_duplicate_keys_trailing_payload_and_oversized_input(self):
        valid = json.dumps({"version": 1, "challenge": "a" * 64})
        for raw in ['{"version":1,"version":1,"challenge":"' + "a" * 64 + '"}', valid + "{}", valid + " " * 513]:
            with self.subTest(size=len(raw)):
                result = self.invoke(raw)
                self.assertEqual(result.returncode, 64)
                self.assertEqual(result.stdout, "")

    def test_rejects_a_terminal_session(self):
        master, slave = pty.openpty()
        try:
            result = subprocess.run([sys.executable, str(TOOL)], stdin=slave, env={"SSH_ORIGINAL_COMMAND": "rngwars-game-preflight-v1"}, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 64)
            self.assertEqual(result.stdout, b"")
        finally:
            os.close(master)
            os.close(slave)

    def test_an_unfinished_request_times_out_without_a_reply(self):
        with subprocess.Popen([sys.executable, str(TOOL)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={"SSH_ORIGINAL_COMMAND": "rngwars-game-preflight-v1"}) as process:
            try:
                process.stdin.write(b'{"version":1')
                process.stdin.flush()
                self.assertEqual(process.wait(timeout=8), 64)
                self.assertEqual(process.stdout.read(), b"")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    unittest.main()
