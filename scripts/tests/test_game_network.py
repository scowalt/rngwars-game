import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import tempfile
import unittest


TOOL = Path(__file__).parents[1] / "game_network.py"
REVISION = "a" * 40
REPOSITORY = "scowalt/rngwars-game"
WORKFLOW = REPOSITORY + "/.github/workflows/game-deployment.yml@refs/heads/main"


class PrivatePreflightCLITests(unittest.TestCase):
    def setUp(self):
        self.area = tempfile.TemporaryDirectory()
        self.addCleanup(self.area.cleanup)
        self.root = Path(self.area.name)
        gh = self.root / "gh"
        gh.write_text("#!" + sys.executable + "\nimport json,sys\nfrom pathlib import Path\nroot=Path(__file__).parent\nargs=sys.argv[1:];assert args[0]=='api' and args[args.index('--method')+1]=='GET'\nroute=args[-1].removeprefix('repos/scowalt/rngwars-game')\nresponses=json.loads((root/'responses.json').read_text());assert route in responses\nprint(json.dumps(responses[route]))\n")
        gh.chmod(0o700)
        identity = {"id": 1442331254}
        self.environment = {"PATH": str(self.root) + os.pathsep + os.environ["PATH"], "HOME": str(self.root), "RUNNER_TEMP": str(self.root), "RUNNER_ENVIRONMENT": "github-hosted", "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_REPOSITORY_ID": "1442331254", "GITHUB_REPOSITORY_OWNER_ID": "1100550", "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": REVISION, "GITHUB_WORKFLOW_SHA": REVISION, "GITHUB_WORKFLOW_REF": WORKFLOW, "GITHUB_RUN_ID": "99", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_ACTOR": "scowalt", "GITHUB_ACTOR_ID": "1100550", "GITHUB_TRIGGERING_ACTOR": "scowalt", "SOURCE_CI_RUN_ID": "42", "APPROVED_REVISION": REVISION, "GAME_PREFLIGHT_OPERATION": "verify-release", "GAME_PRIVATE_PREFLIGHT_ENABLED": "false"}
        self.responses = {"": {**identity, "private": False, "default_branch": "main"}, "/git/ref/heads/main": {"object": {"sha": REVISION}}, "/actions/workflows/ci.yml": {"id": 11, "state": "active", "path": ".github/workflows/ci.yml"}, "/actions/runs/42": {"id": 42, "repository": identity, "head_repository": identity, "event": "push", "run_attempt": 1, "status": "completed", "conclusion": "success", "workflow_id": 11, "path": ".github/workflows/ci.yml", "head_sha": REVISION, "head_branch": "main", "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}, "/contents/.github/workflows/ci.yml?ref=" + REVISION: {"type": "file", "sha": "b" * 40}, "/actions/runs/42/attempts/1/jobs?per_page=100": {"total_count": 3, "jobs": [{"name": name, "status": "completed", "conclusion": "success"} for name in ["Build API (F#)", "Build Frontend (SolidJS)", "Portable SQLite backup and deployment preparation"]]}, "/actions/workflows/game-deployment.yml": {"id": 13, "path": ".github/workflows/game-deployment.yml", "state": "active"}, "/actions/runs/99": {"id": 99, "workflow_id": 13, "path": ".github/workflows/game-deployment.yml", "head_sha": REVISION, "head_branch": "main", "repository": identity, "head_repository": identity, "event": "workflow_dispatch", "run_attempt": 1, "status": "in_progress", "actor": {"id": 1100550}, "triggering_actor": {"id": 1100550}}, "/environments/game-production": {"id": 400, "name": "game-production", "can_admins_bypass": False, "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}, "protection_rules": [{"type": "required_reviewers", "prevent_self_review": False, "reviewers": [{"type": "User", "reviewer": {"id": 1100550}}]}]}, "/environments/game-production/deployment-branch-policies": {"total_count": 1, "branch_policies": [{"name": "main", "type": "branch"}]}, "/actions/runs/99/approvals": [{"state": "approved", "user": {"id": 1100550}, "environments": [{"id": 400, "name": "game-production"}]}], "/actions/runs/99/attempts/1/jobs?per_page=100": {"total_count": 3, "jobs": [{"name": "resolve", "run_id": 99, "status": "completed", "conclusion": "success", "labels": ["ubuntu-24.04"]}, {"name": "Private transport preflight", "run_id": 99, "status": "in_progress", "conclusion": None, "labels": ["ubuntu-24.04"]}, {"name": "Deploy verified game release", "run_id": 99, "status": "completed", "conclusion": "skipped", "labels": ["ubuntu-24.04"]}]} }

    def invoke(self, operation="resolve"):
        (self.root / "responses.json").write_text(json.dumps(self.responses))
        return subprocess.run([sys.executable, str(TOOL), operation], env=self.environment, capture_output=True, text=True, timeout=20)

    def test_resolves_exact_current_main_CI_without_private_network_capability(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"status": "private_preflight_context_only", "controller_revision": REVISION, "run_id": 99, "ci_run_id": 42})
        self.assertFalse((self.root / "rngwars-game-network-99-1").exists())

    def enable_transport(self):
        self.environment.update(GAME_PREFLIGHT_OPERATION="private-preflight", GAME_PRIVATE_PREFLIGHT_ENABLED="true", GITHUB_JOB="preflight", ACTIONS_ID_TOKEN_REQUEST_TOKEN="synthetic-OIDC-request-token", ACTIONS_ID_TOKEN_REQUEST_URL="https://token.actions.githubusercontent.com/fixture", GAME_SSH_PRIVATE_KEY="-----BEGIN OPENSSH PRIVATE KEY-----\nsynthetic-key\n-----END OPENSSH PRIVATE KEY-----\n")
        self.binding = {"client_id": "fixture-client", "audience": "api.tailscale.com/fixture-client", "target_ipv4": "100.90.0.1", "target_port": 22222, "ssh_user": "rngwars-deploy", "host_public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIE5vbktleUZpeHR1cmVPbmx5MDAwMDAwMDAwMDAwMDAw", "denied_probe_ipv4": "100.90.0.2"}
        self.environment["GAME_NETWORK_BINDING"] = json.dumps(self.binding)
        daemon = self.root / "tailscaled"
        daemon.write_text("#!" + sys.executable + "\nimport json,os,signal,socket,sys\nfrom pathlib import Path\nroot=Path(__file__).parent\nassert '--state=mem:' in sys.argv and '--tun=userspace-networking' in sys.argv and '--port=0' in sys.argv\nassert 'ACTIONS_ID_TOKEN_REQUEST_TOKEN' not in os.environ and 'GAME_SSH_PRIVATE_KEY' not in os.environ\npath=next(a.split('=',1)[1] for a in sys.argv if a.startswith('--socket='))\ns=socket.socket(socket.AF_UNIX);s.bind(path);s.listen(1)\n(root/'daemon-pid').write_text(str(os.getpid()))\nsignal.pause()\n")
        daemon.chmod(0o700)
        tailscale = self.root / "tailscale"
        tailscale.write_text("#!" + sys.executable + "\nimport json,os,sys\nfrom pathlib import Path\nroot=Path(__file__).parent\nargs=sys.argv[1:];assert args[0].startswith('--socket=')\nassert 'GAME_SSH_PRIVATE_KEY' not in os.environ and 'GAME_NETWORK_BINDING' not in os.environ\noperation=args[1]\nwith (root/'tailnet-events').open('a') as f:f.write(operation+'\\n')\nif operation=='up':\n if (root/'join-fails').exists(): print('synthetic-private-transport-diagnostic',file=sys.stderr);raise SystemExit(1)\n assert os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']=='synthetic-OIDC-request-token'\n assert '--client-id=fixture-client?ephemeral=true&preauthorized=true' in args and '--audience=api.tailscale.com/fixture-client' in args and '--advertise-tags=tag:rngwars-game-ci' in args\n assert '--accept-dns=false' in args and '--accept-routes=false' in args and '--ssh=false' in args and '--shields-up=true' in args\n raise SystemExit(0)\nif operation=='status':\n print(json.dumps({'BackendState':'Running','Self':{'Tags':['tag:server'] if (root/'wrong-tag').exists() else ['tag:rngwars-game-ci']}}));raise SystemExit(0)\nif operation=='logout':raise SystemExit(0)\nif operation=='nc':raise SystemExit(0 if (root/'negative-connects').exists() else 1)\nraise SystemExit(1)\n")
        tailscale.chmod(0o700)
        ssh = self.root / "ssh"
        ssh.write_text("#!" + sys.executable + "\nimport ctypes,json,os,stat,sys,time\nfrom pathlib import Path\nroot=Path(__file__).parent\nif (root/'hold-ssh').exists():\n ctypes.CDLL(None).prctl(1,15);(root/'ssh-entered').touch();time.sleep(20)\nassert 'GAME_SSH_PRIVATE_KEY' not in os.environ and 'ACTIONS_ID_TOKEN_REQUEST_TOKEN' not in os.environ\nargs=sys.argv[1:];assert '-T' in args and args[-1]=='rngwars-game-preflight-v1'\nassert 'StrictHostKeyChecking=yes' in args and 'IdentitiesOnly=yes' in args and 'IdentityAgent=none' in args and 'ClearAllForwardings=yes' in args\nkey=Path(args[args.index('-i')+1]);assert stat.S_IMODE(key.stat().st_mode)==0o600 and 'synthetic-key' in key.read_text() and key.read_text().endswith('\\n')\nassert any(a.startswith('ProxyCommand=') and 'nc %h %p' in a for a in args)\nrequest=json.load(sys.stdin);print(json.dumps({'version':1,'challenge':'0'*64 if (root/'wrong-challenge').exists() else request['challenge'],'status':'restricted_transport_only'}))\n")
        ssh.chmod(0o700)

    def test_uses_ephemeral_OIDC_transport_checks_negative_routes_and_cleans_its_own_state(self):
        self.enable_transport()
        result = self.invoke("probe")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "private_transport_verified_no_deployment")
        self.assertEqual((self.root / "tailnet-events").read_text().splitlines(), ["up", "status", "nc", "nc", "nc", "logout"])
        self.assertFalse((self.root / "rngwars-game-network-99-1").exists())
        pid = int((self.root / "daemon-pid").read_text())
        self.assertFalse(Path("/proc", str(pid)).exists())
        self.assertNotIn("synthetic-key", result.stdout + result.stderr)
        self.assertNotIn("100.90.0", result.stdout + result.stderr)

    def test_cleanup_is_safe_when_the_private_step_never_created_state(self):
        result = self.invoke("cleanup")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "owned_private_state_absent")

    def test_cleanup_refuses_to_delete_a_directory_not_created_by_this_run(self):
        foreign = self.root / "rngwars-game-network-99-1"
        foreign.mkdir(mode=0o700)
        (foreign / "unrelated").write_text("preserve")
        result = self.invoke("cleanup")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((foreign / "unrelated").read_text(), "preserve")

    def test_cleanup_releases_an_owned_daemon_and_credentials_after_controller_interruption(self):
        self.enable_transport()
        (self.root / "hold-ssh").touch()
        (self.root / "responses.json").write_text(json.dumps(self.responses))
        with subprocess.Popen([sys.executable, str(TOOL), "probe"], env=self.environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as controller:
            try:
                deadline = time.monotonic() + 10
                while not (self.root / "ssh-entered").exists():
                    self.assertIsNone(controller.poll())
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.02)
                controller.kill()
                controller.wait(timeout=5)
                result = self.invoke("cleanup")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["status"], "owned_private_state_cleaned")
                self.assertFalse((self.root / "rngwars-game-network-99-1").exists())
            finally:
                if controller.poll() is None:
                    controller.kill()
                    controller.wait(timeout=5)
                pid_file = self.root / "daemon-pid"
                if pid_file.exists():
                    pid = int(pid_file.read_text())
                    command = Path("/proc", str(pid), "cmdline")
                    if command.exists() and str(self.root / "tailscaled").encode() in command.read_bytes():
                        os.kill(pid, signal.SIGTERM)

    def test_untrusted_contexts_cannot_start_private_networking(self):
        self.enable_transport()
        original = dict(self.environment)
        for change in [{"GITHUB_REF": "refs/pull/1/merge"}, {"GITHUB_EVENT_NAME": "pull_request"}, {"GITHUB_RUN_ATTEMPT": "2"}, {"GITHUB_ACTOR_ID": "7"}, {"GITHUB_WORKFLOW_SHA": "b" * 40}, {"RUNNER_ENVIRONMENT": "self-hosted"}, {"GAME_PRIVATE_PREFLIGHT_ENABLED": "false"}]:
            with self.subTest(change=list(change)):
                self.environment = {**original, **change}
                result = self.invoke("probe")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "daemon-pid").exists())
                self.assertFalse((self.root / "rngwars-game-network-99-1").exists())

    def test_missing_review_or_changed_environment_fails_before_credentials_are_staged(self):
        self.enable_transport()
        original = json.dumps(self.responses)
        for case in ["unreviewed", "other-reviewer", "bypass", "branch", "runner", "stale-CI"]:
            with self.subTest(case=case):
                self.responses = json.loads(original)
                if case == "unreviewed":
                    self.responses["/actions/runs/99/approvals"] = []
                elif case == "other-reviewer":
                    self.responses["/actions/runs/99/approvals"][0]["user"]["id"] = 7
                elif case == "bypass":
                    self.responses["/environments/game-production"]["can_admins_bypass"] = True
                elif case == "branch":
                    self.responses["/environments/game-production/deployment-branch-policies"]["branch_policies"][0]["name"] = "*"
                elif case == "runner":
                    self.responses["/actions/runs/99/attempts/1/jobs?per_page=100"]["jobs"][1]["labels"] = ["self-hosted", "ubuntu-24.04"]
                else:
                    self.responses["/actions/runs/42"]["created_at"] = "2020-01-01T00:00:00Z"
                result = self.invoke("probe")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "daemon-pid").exists())
                self.assertFalse((self.root / "rngwars-game-network-99-1").exists())

    def test_an_unexpected_success_on_a_negative_route_blocks_acceptance_and_cleans_up(self):
        self.enable_transport()
        (self.root / "negative-connects").touch()
        result = self.invoke("probe")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("private_negative_route_connected", result.stderr)
        self.assertEqual((self.root / "tailnet-events").read_text().splitlines()[-1], "logout")
        self.assertFalse((self.root / "rngwars-game-network-99-1").exists())

    def test_rejects_public_targets_and_unsafe_identity_bindings_without_joining(self):
        self.enable_transport()
        for change in [{"target_ipv4": "203.0.113.1"}, {"target_port": 22}, {"ssh_user": "root"}, {"audience": "other"}, {"host_public_key": "ssh-ed25519 invalid\ncommand"}, {"denied_probe_ipv4": self.binding["target_ipv4"]}]:
            with self.subTest(change=list(change)):
                self.environment["GAME_NETWORK_BINDING"] = json.dumps({**self.binding, **change})
                result = self.invoke("probe")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.root / "daemon-pid").exists())
                self.assertFalse((self.root / "rngwars-game-network-99-1").exists())

    def test_private_join_failure_cleans_up_without_exposing_native_diagnostics(self):
        self.enable_transport()
        (self.root / "join-fails").touch()
        result = self.invoke("probe")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("private_OIDC_join_failed", result.stderr)
        self.assertNotIn("synthetic-private-transport-diagnostic", result.stdout + result.stderr)
        self.assertFalse((self.root / "rngwars-game-network-99-1").exists())
        self.assertEqual((self.root / "tailnet-events").read_text().splitlines()[-1], "logout")

    def test_wrong_node_tag_and_replayed_challenge_cannot_claim_verified_transport(self):
        for marker, code in [("wrong-tag", "private_node_identity"), ("wrong-challenge", "private_probe_reply")]:
            with self.subTest(marker=marker):
                self.enable_transport()
                path = self.root / marker
                path.touch()
                result = self.invoke("probe")
                path.unlink()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(code, result.stderr)
                self.assertFalse((self.root / "rngwars-game-network-99-1").exists())

    def test_restores_the_private_key_final_newline_before_calling_OpenSSH(self):
        self.enable_transport()
        self.environment["GAME_SSH_PRIVATE_KEY"] = self.environment["GAME_SSH_PRIVATE_KEY"].rstrip()
        result = self.invoke("probe")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "rngwars-game-network-99-1").exists())

    def test_reviewed_deploy_checks_transport_then_sends_only_the_private_run_envelope(self):
        self.enable_transport()
        self.environment.update(GAME_PREFLIGHT_OPERATION="deploy", GAME_DEPLOYMENT_ENABLED="true", GITHUB_JOB="deploy", GH_TOKEN="synthetic-job-read-token", IMAGE_SOURCE_REVISION="b" * 40, EXPECTED_IMAGE_DIGEST="sha256:" + "c" * 64, PUBLICATION_RUN_ID="77")
        jobs = self.responses["/actions/runs/99/attempts/1/jobs?per_page=100"]
        jobs["total_count"] = 3
        jobs["jobs"][1].update(status="completed", conclusion="skipped")
        jobs["jobs"][-1].update(status="in_progress", conclusion=None)
        (self.root / "ssh").rename(self.root / "probe-ssh")
        ssh = self.root / "ssh"
        ssh.write_text("#!" + sys.executable + "\nimport json,os,sys\nfrom pathlib import Path\nr=Path(__file__).parent\nif sys.argv[-1]=='rngwars-game-preflight-v1': os.execv(str(r/'probe-ssh'),[str(r/'probe-ssh'),*sys.argv[1:]])\nassert sys.argv[-1]=='rngwars-game-deploy-v1' and 'GH_TOKEN' not in os.environ\nassert json.load(sys.stdin)=={'version':1,'run_id':99,'github_token':'synthetic-job-read-token'}\n(r/'deploy-called').touch()\nprint(json.dumps({'status':'game_deployed','run_id':99,'controller_revision':'" + REVISION + "','image_digest':'sha256:" + "c" * 64 + "','source_revision':'" + "b" * 40 + "','publication_run_id':77}))\n")
        ssh.chmod(0o700)
        result = self.invoke("deploy")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "game_deployed")
        self.assertTrue((self.root / "deploy-called").exists())
        self.assertNotIn("synthetic-job-read-token", result.stdout + result.stderr)
        self.assertFalse((self.root / "rngwars-game-network-99-1").exists())
        self.assertEqual((self.root / "tailnet-events").read_text().splitlines()[-1], "logout")
        self.environment["GAME_DEPLOYMENT_ENABLED"] = "false"
        (self.root / "deploy-called").unlink()
        blocked = self.invoke("deploy")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertFalse((self.root / "deploy-called").exists())


if __name__ == "__main__":
    unittest.main()
