import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[2]


class UpdaterUnitTests(unittest.TestCase):
    def test_rendered_socket_worker_is_local_root_only_and_does_not_relax_SSH(self):
        source = ROOT / "ops/production/game-deployment"
        with tempfile.TemporaryDirectory() as directory:
            area = Path(directory)
            socket = (source / "rngwars-game-updater.socket").read_text()
            service = (source / "rngwars-game-updater@.service").read_text().format(helper_directory=area, policy_file=area / "policy.json", tool_directory=area / "bin", state_directory=area / "state", work_directory=area / "work", data_directory=area / "data", backup_state_directory=area / "backup-state")
            (area / "rngwars-game-updater.socket").write_text(socket)
            (area / "rngwars-game-updater@.service").write_text(service)
            for name in ["sysinit.target", "basic.target", "sockets.target", "network-online.target"]:
                (area / name).write_text("[Unit]\nDefaultDependencies=no\n")
            result = subprocess.run(["systemd-analyze", "verify", str(area / "rngwars-game-updater.socket"), str(area / "rngwars-game-updater@.service")], env={"PATH": os.environ["PATH"], "SYSTEMD_UNIT_PATH": directory}, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("ListenStream=/run/rngwars-game-updater.sock", socket)
            self.assertIn("SocketMode=0660", socket)
            self.assertIn("SocketGroup=rngwars-deploy", socket)
            self.assertIn("Accept=yes", socket)
            self.assertIn("MaxConnections=1", socket)
            for setting in ["User=root", "NoNewPrivileges=yes", "ProtectSystem=strict", "ProtectHome=yes", "StandardInput=socket", "StandardOutput=socket", "KillMode=control-group"]:
                self.assertIn(setting, service)
            self.assertIn("SuccessExitStatus=75", service)
            self.assertIn("AmbientCapabilities=CAP_SETUID", service)
            self.assertIn("CapabilityBoundingSet=CAP_CHOWN CAP_DAC_OVERRIDE CAP_FOWNER CAP_SETUID CAP_SETGID", service)
            self.assertIn("NoNewPrivileges=yes", (source / "rngwars-game-ssh.service").read_text())


if __name__ == "__main__":
    unittest.main()
