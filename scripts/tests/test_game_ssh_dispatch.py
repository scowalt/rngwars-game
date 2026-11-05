import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest


TOOL = Path(__file__).parents[1] / "game_ssh_dispatch.py"


class DispatchCLITests(unittest.TestCase):
    def test_only_exact_deploy_verb_relays_bounded_input_to_the_selected_local_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "worker.sock")
            request = {"version": 1, "run_id": 501, "github_token": "synthetic-transient-job-read-token"}
            reply = {"status": "game_deployed", "run_id": 501, "controller_revision": "a" * 40, "image_digest": "sha256:" + "b" * 64, "source_revision": "c" * 40, "publication_run_id": 77}
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(path)
                server.listen(1)
                server.settimeout(10)
                received = []
                def respond():
                    connection, _ = server.accept()
                    with connection:
                        content = bytearray()
                        while chunk := connection.recv(8192):
                            content.extend(chunk)
                        received.append(json.loads(content))
                        connection.sendall(json.dumps(reply).encode())
                worker = threading.Thread(target=respond)
                worker.start()
                result = subprocess.run([sys.executable, "-I", str(TOOL), "--socket", path], env={"PATH": os.environ["PATH"], "SSH_ORIGINAL_COMMAND": "rngwars-game-deploy-v1"}, input=json.dumps(request), capture_output=True, text=True, timeout=15)
                worker.join(timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), reply)
                self.assertEqual(received, [request])
                self.assertNotIn(request["github_token"], result.stdout + result.stderr)
                rejected = subprocess.run([sys.executable, "-I", str(TOOL), "--socket", path], env={"PATH": os.environ["PATH"], "SSH_ORIGINAL_COMMAND": "sh -c echo-owned"}, input="{}", capture_output=True, text=True, timeout=10)
                self.assertEqual(rejected.returncode, 64)


if __name__ == "__main__":
    unittest.main()
