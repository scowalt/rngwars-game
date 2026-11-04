import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[2]
TEMPLATE = ROOT / "ops" / "production" / "game-deployment" / "sshd_config.template"


class PrivateSSHConfigurationTests(unittest.TestCase):
    def test_real_sshd_enforces_the_single_user_key_and_command_without_forwarding(self):
        sshd = shutil.which("sshd") or "/usr/sbin/sshd"
        self.assertTrue(Path(sshd).is_file(), "Install the OpenSSH server CLI for configuration validation; no server is started.")
        with tempfile.TemporaryDirectory() as directory:
            area = Path(directory)
            key = area / "host-key"
            result = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            policy = area / "sshd.conf"
            policy.write_text(TEMPLATE.read_text().format(port=24567, listen_address="127.0.0.2", host_key=key, pid_file=area / "pid", authorized_keys=area / "authorized-keys", user="nobody", forced_command="/usr/bin/false"))
            result = subprocess.run([sshd, "-T", "-f", str(policy), "-C", "user=nobody,host=fixture,addr=127.0.0.1"], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            settings = {}
            for line in result.stdout.splitlines():
                name, _, value = line.partition(" ")
                settings.setdefault(name, []).append(value)
            expected = {"listenaddress": ["127.0.0.2:24567"], "allowusers": ["nobody"], "authenticationmethods": ["publickey"], "pubkeyauthentication": ["yes"], "passwordauthentication": ["no"], "kbdinteractiveauthentication": ["no"], "permitrootlogin": ["no"], "disableforwarding": ["yes"], "allowtcpforwarding": ["no"], "allowstreamlocalforwarding": ["no"], "allowagentforwarding": ["no"], "x11forwarding": ["no"], "permittunnel": ["no"], "permittty": ["no"], "permituserrc": ["no"], "permituserenvironment": ["no"], "forcecommand": ["/usr/bin/false"], "maxsessions": ["1"], "authorizedkeysfile": [str(area / "authorized-keys")]}
            for key, value in expected.items():
                with self.subTest(setting=key):
                    self.assertEqual(settings.get(key), value)
            self.assertNotIn("acceptenv", settings)
            self.assertNotIn("subsystem", settings)

    def test_rendered_probe_unit_provides_OpenSSH_runtime_without_starting_a_service(self):
        template = ROOT / "ops" / "production" / "game-deployment" / "rngwars-game-ssh.service"
        with tempfile.TemporaryDirectory() as directory:
            area = Path(directory)
            text = template.read_text().format(configuration_file=area / "sshd.conf")
            unit = area / "rngwars-game-ssh.service"
            unit.write_text(text)
            for name in ["sysinit.target", "basic.target", "network-online.target"]:
                (area / name).write_text("[Unit]\nDefaultDependencies=no\n")
            environment = {"PATH": os.environ["PATH"], "SYSTEMD_UNIT_PATH": str(area)}
            blocked = subprocess.run(["systemd-analyze", "verify", str(unit)], env=environment, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("Unit tailscaled.service not found", blocked.stderr)
            (area / "tailscaled.service").write_text("[Service]\nType=oneshot\nExecStart=/usr/bin/true\n")
            result = subprocess.run(["systemd-analyze", "verify", str(unit)], env=environment, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("RuntimeDirectory=rngwars-game-ssh sshd", text)
            self.assertIn("RuntimeDirectoryPreserve=yes", text)
            self.assertIn("NoNewPrivileges=yes", text)
            self.assertIn("ProtectSystem=strict", text)
            self.assertNotIn("ExecStartPre=", text)


if __name__ == "__main__":
    unittest.main()
