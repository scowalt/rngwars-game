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


if __name__ == "__main__":
    unittest.main()
