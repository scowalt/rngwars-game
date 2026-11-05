from contextlib import closing
import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import unittest

import test_game_deploy_authority as authority_fixtures
import test_game_release as release_fixtures


TOOL = Path(__file__).parents[1] / "game_updater.py"
RECOVERY = TOOL.with_name("game_recovery.py")


class UpdaterCLITests(unittest.TestCase):
    def setUp(self):
        self.auth = authority_fixtures.DeploymentAuthorityCLITests()
        self.auth.setUp()
        self.addCleanup(self.auth.doCleanups)
        self.release = release_fixtures.ReleaseVerificationCLITests()
        self.release.setUp()
        self.addCleanup(self.release.doCleanups)
        self.root = self.auth.root
        self.auth.request.update(image_source_revision=release_fixtures.REVISION, image_digest=release_fixtures.DIGEST, publication_run_id=77)
        self.assertEqual(self.auth.invoke().returncode, 0)
        for name, value in [("run", self.release.run), ("jobs", self.release.jobs), ("statement", self.release.statement)]:
            (self.release.root / (name + ".json")).write_text(json.dumps(value))
        (self.root / "gh").rename(self.root / "github-api")
        self.executable("gh", "import os,sys\nfrom pathlib import Path\nr=Path(__file__).parent\np=str(r/'github-api') if sys.argv[1]=='api' else " + repr(str(self.release.root / "gh")) + "\nos.execv(p,[p,*sys.argv[1:]])\n")
        self.executable("curl", "import os,sys\nif sys.argv[-1]=='http://169.254.169.254/hetzner/v1/metadata/instance-id': print('12345')\nelse:\n p=" + repr(str(self.release.root / "curl")) + ";os.execv(p,[p,*sys.argv[1:]])\n")
        self.executable("systemctl", "import datetime\nprint((datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=1)).strftime('%a %Y-%m-%d %H:%M:%S UTC'))\n")
        for name in ["state", "work", "data", "backup-state", "credentials"]:
            (self.root / name).mkdir(mode=0o700)
        self.database = self.root / "data/game.sqlite3"
        previous = os.umask(0o077)
        try:
            with closing(sqlite3.connect(self.database)) as db:
                db.executescript("PRAGMA application_id=1380861783; CREATE TABLE users(id TEXT PRIMARY KEY,token TEXT); INSERT INTO users VALUES('player','synthetic-player-token'); CREATE TABLE SchemaVersions(id INTEGER PRIMARY KEY,name TEXT); INSERT INTO SchemaVersions VALUES(1,'first'),(2,'second');")
        finally:
            os.umask(previous)
        description = self.describe(self.database)
        credentials = self.root / "credentials"
        password = credentials / "password"
        password.write_text("synthetic-password")
        password.chmod(0o600)
        repository = self.root / "restic-repository"
        backup_policy = credentials / "policy.json"
        backup_policy.write_text(json.dumps({"repository": str(repository), "host": "fixture", "tag": "fixture", "image_repository": release_fixtures.IMAGE, "data_directory": str(self.database.parent)}))
        backup_policy.chmod(0o600)
        env = {"PATH": os.environ["PATH"], "RESTIC_REPOSITORY": str(repository), "RESTIC_PASSWORD_FILE": str(password), "SQLITE_BACKUP_STATE_DIR": str(self.root / "backup-state"), "SQLITE_BACKUP_POLICY_FILE": str(backup_policy)}
        r = subprocess.run(["restic", "init"], env=env, capture_output=True)
        self.assertEqual(r.returncode, 0)
        runtime = credentials / "runtime.env"
        runtime.write_text("".join(k + "=" + v + "\n" for k, v in env.items() if k != "PATH"))
        runtime.chmod(0o600)
        self.policy = {"version": 1, "host_id": "12345", "architecture": os.uname().machine, "authority_policy": str(self.root / "policy.json"), "state_directory": str(self.root / "state"), "work_directory": str(self.root / "work"), "database": str(self.database), "data_uid": os.geteuid(), "data_gid": os.getegid(), "data_device": description["device"], "data_inode": description["inode"], "schema": description["schema"], "backup_environment": str(runtime), "workload": "rngwars-game", "network": "rngwars-game", "network_id": "1" * 64, "owner_key": "info.rngwars.owner", "owner_value": "fixture-controller", "initial_container": "2" * 64, "initial_image": release_fixtures.IMAGE + "@sha256:" + "3" * 64, "peer_uid": 10002, "peer_gid": 10002, "health_seconds": 1}
        self.runtime_policy = self.root / "runtime-policy.json"
        self.runtime_policy.write_text(json.dumps(self.policy))
        self.runtime_policy.chmod(0o400)
        old = {"Id": "2" * 64, "Name": "/rngwars-game", "State": {"Running": True}, "Config": {"Image": self.policy["initial_image"], "User": f"{os.geteuid()}:{os.getegid()}", "Labels": {self.policy["owner_key"]: self.policy["owner_value"]}, "Entrypoint": ["/app/game-entrypoint.sh"], "Cmd": ["dotnet", "RNGWars.Api.dll"]}, "HostConfig": {"PortBindings": {}, "Init": True, "ReadonlyRootfs": True, "Privileged": False, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges"], "NetworkMode": self.policy["network"]}, "Mounts": [{"Type": "bind", "Source": str(self.database.parent), "Destination": "/data", "RW": True}], "NetworkSettings": {"Networks": {self.policy["network"]: {"NetworkID": self.policy["network_id"], "Aliases": ["game"]}}}}
        (self.root / "docker-state.json").write_text(json.dumps({"containers": {old["Id"]: old}, "next": 4, "events": [], "fault": None}))
        image = json.loads((self.release.root / "config.json").read_text())
        (self.root / "image.json").write_text(json.dumps({"Id": release_fixtures.DIGEST, "Descriptor": {"digest": release_fixtures.DIGEST}, "Os": "linux", "Architecture": "arm64", "Config": image["config"], "RootFS": {"Layers": image["rootfs"]["diff_ids"]}}))
        shutil.copyfile(Path(__file__).with_name("fixtures") / "updater_docker.py", self.root / "docker-body.py")
        self.executable("docker", "from pathlib import Path\nexec(compile(Path(__file__).with_name('docker-body.py').read_text(),'docker-fixture','exec'))\n")
        self.environment = {"PATH": str(self.root) + os.pathsep + os.environ["PATH"], "HOME": str(self.root)}

    def executable(self, name, body):
        path = self.root / name
        path.write_text("#!" + sys.executable + "\n" + body)
        path.chmod(0o700)

    def describe(self, path):
        result = subprocess.run([sys.executable, str(RECOVERY), "inspect", str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def command(self, operation="apply"):
        return subprocess.run([sys.executable, str(TOOL), operation, "--policy", str(self.runtime_policy)], input=json.dumps(self.auth.envelope) if operation == "apply" else "", capture_output=True, text=True, env=self.environment, timeout=90)

    def test_updates_only_the_captured_game_preserving_data_and_the_previous_container(self):
        before = self.describe(self.database)
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "game_deployed")
        self.assertEqual(receipt["image_digest"], release_fixtures.DIGEST)
        self.assertEqual(self.describe(self.database), before)
        status = self.command("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["last_outcome"], "game_deployed")
        self.assertNotIn(authority_fixtures.TOKEN, result.stdout + result.stderr)

    def fault(self, name):
        path = self.root / "docker-state.json"
        value = json.loads(path.read_text())
        value["fault"] = name
        path.write_text(json.dumps(value))

    def test_failed_live_health_restores_only_the_captured_previous_container(self):
        self.fault("live-health")
        before = self.describe(self.database)
        result = self.command()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "game_rolled_back")
        self.assertEqual(self.describe(self.database), before)
        self.assertEqual(json.loads(self.command("status").stdout)["last_outcome"], "game_rolled_back")
        inspected = subprocess.run([str(self.root / "docker"), "--host", "unix:///var/run/docker.sock", "--config", str(self.root / "state/docker-config"), "inspect", self.policy["initial_container"]], env=self.environment, capture_output=True, text=True)
        old = json.loads(inspected.stdout)[0]
        self.assertTrue(old["State"]["Running"])
        self.assertEqual(old["Name"], "/rngwars-game")

    def test_changed_live_records_require_operator_recovery_instead_of_database_rewind(self):
        self.fault("live-data-change")
        before = self.describe(self.database)
        result = self.command()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "operator_recovery_required")
        after = self.describe(self.database)
        self.assertEqual(after["inode"], before["inode"])
        self.assertNotEqual(after["content"], before["content"])
        self.assertTrue(json.loads(self.command("status").stdout)["operator_recovery_required"])
        retry = self.command()
        self.assertNotEqual(retry.returncode, 0)
        self.assertIn("updater_operator_recovery_required", retry.stderr)

    def test_schema_changing_candidate_never_stops_the_live_game(self):
        self.fault("candidate-schema")
        before = self.describe(self.database)
        result = self.command()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "deployment_blocked_before_live_change")
        self.assertEqual(self.describe(self.database), before)
        events = json.loads((self.root / "docker-state.json").read_text())["events"]
        self.assertFalse(any(event[0] in {"stop", "rename", "start"} and self.policy["initial_container"] in event for event in events))

    def test_completed_attempt_cannot_be_replayed_and_contains_no_transient_token(self):
        self.assertEqual(self.command().returncode, 0)
        again = self.command()
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("updater_attempt_already_consumed", again.stderr)
        for path in (self.root / "state").rglob("*"):
            if path.is_file():
                self.assertNotIn(authority_fixtures.TOKEN.encode(), path.read_bytes())

    def test_unknown_workload_or_storage_is_rejected_before_any_container_creation(self):
        path = self.root / "docker-state.json"
        value = json.loads(path.read_text())
        value["containers"][self.policy["initial_container"]]["Config"]["User"] = "0:0"
        path.write_text(json.dumps(value))
        result = self.command()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "deployment_blocked_before_live_change")
        self.assertFalse(any(event[0] in {"create", "start", "stop", "rename"} for event in json.loads(path.read_text())["events"]))

    def test_durable_unfinished_attempt_blocks_new_mutations(self):
        path = self.root / "state/inflight.json"
        path.write_text('{"run_id":500}')
        path.chmod(0o600)
        result = self.command()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("updater_operator_recovery_required", result.stderr)
        self.assertEqual(json.loads((self.root / "docker-state.json").read_text())["events"], [])

    def test_ambiguous_create_is_not_retried_or_allowed_to_stop_the_current_game(self):
        self.fault("ambiguous-create")
        result = self.command()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "operator_recovery_required")
        self.assertTrue(json.loads(self.command("status").stdout)["operator_recovery_required"])
        events = json.loads((self.root / "docker-state.json").read_text())["events"]
        self.assertEqual(sum(event[0] == "create" for event in events), 1)
        self.assertFalse(any(event[0] in {"stop", "start", "rename"} for event in events))
        self.assertNotIn("private-Docker-diagnostic", result.stdout + result.stderr)

    def test_changed_entrypoint_is_not_a_known_game_workload(self):
        path = self.root / "docker-state.json"
        value = json.loads(path.read_text())
        value["containers"][self.policy["initial_container"]]["Config"]["Entrypoint"] = ["/bin/sh"]
        path.write_text(json.dumps(value))
        result = self.command()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "deployment_blocked_before_live_change")
        self.assertFalse(any(event[0] in {"create", "start", "stop", "rename"} for event in json.loads(path.read_text())["events"]))


if __name__ == "__main__":
    unittest.main()
