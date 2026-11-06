import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, timeout=180, **kwargs)
    if result.returncode:
        raise RuntimeError("native_updater_fixture_command_failed")
    return result.stdout


def sandbox_identity_check(base):
    state = base / "capability-check-state"
    state.mkdir(mode=0o700)
    text = (ROOT / "ops/production/game-deployment/rngwars-game-updater@.service").read_text().format(helper_directory=base / "helpers", policy_file=state / "unused.json", tool_directory=base / "bin", state_directory=state, work_directory=base / "work", data_directory=base / "data", backup_state_directory=base / "backup-state")
    names = {"User", "Group", "NoNewPrivileges", "PrivateTmp", "ProtectSystem", "ProtectHome", "ProtectKernelTunables", "ProtectKernelModules", "ProtectKernelLogs", "ProtectControlGroups", "RestrictSUIDSGID", "LockPersonality", "RestrictRealtime", "RestrictAddressFamilies", "CapabilityBoundingSet", "AmbientCapabilities", "ReadWritePaths", "MemoryMax", "TasksMax", "LimitCORE"}
    args = ["systemd-run", "--unit=rngwars-updater-native-capabilities-" + str(os.getpid()), "--collect", "--wait", "--pipe"]
    for line in text.splitlines():
        if line.partition("=")[0] in names:
            args.extend(["--property", line])
    child = "import json,os; from pathlib import Path; values={line.partition(':')[0]:line.partition(':')[2].strip() for line in Path('/proc/self/status').read_text().splitlines() if line.startswith(('CapPrm:','CapEff:','CapAmb:','NoNewPrivs:'))}; print(json.dumps({'uid':os.geteuid(),'gid':os.getegid(),**values}))"
    program = "import json,subprocess; result=subprocess.run(['/usr/bin/setpriv','--reuid=10001','--regid=10001','--clear-groups','--no-new-privs','/usr/bin/python3','-I','-c'," + repr(child) + "],capture_output=True,text=True); assert result.returncode==0,'sandbox_identity_drop_failed'; value=json.loads(result.stdout); assert value['uid']==value['gid']==10001 and value['NoNewPrivs']=='1' and all(int(value[key],16)==0 for key in ['CapPrm','CapEff','CapAmb']); print('sandboxed_identity_drop_verified')"
    output = run([*args, "/usr/bin/python3", "-I", "-c", program])
    assert b"sandboxed_identity_drop_verified" in output


def main():
    assert os.geteuid() == 0 and os.uname().machine == "aarch64"
    assert os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted" and os.environ.get("GITHUB_REPOSITORY_ID") == "1442331254"
    assert len(sys.argv) == 2 and re.fullmatch(r"rngwars-native:[a-f0-9]{40}", sys.argv[1])
    assert not any(name in os.environ for name in ["GAME_SSH_PRIVATE_KEY", "GAME_NETWORK_BINDING", "AWS_SECRET_ACCESS_KEY"])
    docker = shutil.which("docker")
    assert docker and shutil.which("restic")
    for arguments in [["inspect", "rngwars-game"], ["network", "inspect", "rngwars-game"]]:
        assert subprocess.run([docker, *arguments], capture_output=True).returncode != 0
    sys.path.insert(0, str(ROOT / "scripts/tests"))
    import test_game_updater
    fixture = test_game_updater.UpdaterCLITests()
    fixture.setUp()
    base = Path(tempfile.mkdtemp(prefix="rngwars-updater-native-", dir="/run"))
    base.chmod(0o755)
    created = []
    network = None
    try:
        helpers = base / "helpers"
        helpers.mkdir(mode=0o755)
        for source in (ROOT / "scripts").glob("*.py"):
            shutil.copyfile(source, helpers / source.name)
            (helpers / source.name).chmod(0o444)
        tools = base / "bin"
        tools.mkdir(mode=0o755)
        shutil.copyfile(shutil.which("restic"), tools / "restic")
        (tools / "restic").chmod(0o555)
        fixture.environment["PATH"] = str(fixture.root) + ":" + str(tools) + ":/usr/bin:/bin"
        for name in ["data", "work", "backup-state", "credentials", "repository-parent"]:
            path = base / name
            path.mkdir(mode=0o700)
            os.chown(path, 10001, 10001)
        sandbox_identity_check(base)
        database = base / "data/game.sqlite3"
        run([docker, "run", "--rm", "--init", "--network", "none", "--user", "10001:10001", "--mount", "type=bind,src=" + str(database.parent) + ",dst=/data", "--entrypoint", "dotnet", sys.argv[1], "RNGWars.Api.dll", "init-db", "/data/game.sqlite3"])
        derived = "rngwars-updater-native-fixture:" + str(os.getpid())
        recipe = "FROM " + sys.argv[1] + "\nLABEL org.opencontainers.image.revision=" + "a" * 40 + " org.opencontainers.image.source=https://github.com/scowalt/rngwars-game\n"
        run([docker, "build", "--tag", derived, "-"], input=recipe.encode())
        image = json.loads(run([docker, "image", "inspect", derived]))[0]
        config = {"architecture": "arm64", "os": "linux", "config": image["Config"], "rootfs": {"type": "layers", "diff_ids": image["RootFS"]["Layers"]}}
        config_raw = json.dumps(config).encode()
        manifest = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json", "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": "sha256:" + hashlib.sha256(config_raw).hexdigest(), "size": len(config_raw)}, "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar", "digest": value, "size": 1} for value in config["rootfs"]["diff_ids"]]}
        manifest_raw = json.dumps(manifest).encode()
        digest = "sha256:" + hashlib.sha256(manifest_raw).hexdigest()
        reference = "ghcr.io/scowalt/rngwars-game-releases@" + digest
        (fixture.release.root / "config.json").write_bytes(config_raw)
        (fixture.release.root / "manifest.json").write_bytes(manifest_raw)
        fixture.release.statement["subject"][0]["digest"]["sha256"] = digest.split(":")[1]
        (fixture.release.root / "statement.json").write_text(json.dumps(fixture.release.statement))
        credentials = base / "credentials"
        password = credentials / "password"
        password.write_text("synthetic-native-recovery-password")
        policy_file = credentials / "policy.json"
        repository = base / "repository-parent/repository"
        policy_file.write_text(json.dumps({"repository": str(repository), "host": "native-fixture", "tag": "native-fixture", "image_repository": "ghcr.io/scowalt/rngwars-game-releases", "data_directory": str(database.parent)}))
        runtime = credentials / "runtime.env"
        environment = {"PATH": str(tools) + ":/usr/bin:/bin", "RESTIC_REPOSITORY": str(repository), "RESTIC_PASSWORD_FILE": str(password), "SQLITE_BACKUP_STATE_DIR": str(base / "backup-state"), "SQLITE_BACKUP_POLICY_FILE": str(policy_file)}
        runtime.write_text("".join(k + "=" + v + "\n" for k, v in environment.items() if k != "PATH"))
        for path in [password, policy_file, runtime]:
            path.chmod(0o600)
            os.chown(path, 10001, 10001)
        user = ["setpriv", "--reuid=10001", "--regid=10001", "--clear-groups", "--no-new-privs"]
        run([*user, str(tools / "restic"), "init"], env=environment)
        description = json.loads(run([*user, "/usr/bin/python3", str(helpers / "game_recovery.py"), "inspect", str(database)]))
        network = run([docker, "network", "create", "--internal", "rngwars-game"]).decode().strip()
        initial = run([docker, "run", "-d", "--init", "--name", "rngwars-game", "--network", "rngwars-game", "--network-alias", "game", "--user", "10001:10001", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--mount", "type=bind,src=" + str(database.parent) + ",dst=/data", "-e", "DATABASE_PATH=/data/game.sqlite3", "-e", "ASPNETCORE_URLS=http://0.0.0.0:5000", "-e", "SENTRY_DSN=", "--label", "info.rngwars.owner=fixture-controller", image["Id"]]).decode().strip()
        created.append(initial)
        for _ in range(60):
            health = subprocess.run([docker, "exec", initial, "curl", "-fsS", "http://127.0.0.1:5000/api/health"], capture_output=True)
            if health.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("native_initial_health")
        player = json.loads(run([docker, "exec", initial, "curl", "-fsS", "-X", "POST", "http://127.0.0.1:5000/api/users/anonymous"]))
        token = player["token"]
        user_id = player["user"]["id"]
        assert token
        fixture.policy.update(architecture="aarch64", database=str(database), data_uid=10001, data_gid=10001, data_device=description["device"], data_inode=description["inode"], schema=description["schema"], work_directory=str(base / "work"), backup_environment=str(runtime), initial_container=initial, network_id=network, health_seconds=30)
        fixture.runtime_policy.chmod(0o600)
        fixture.runtime_policy.write_text(json.dumps(fixture.policy))
        fixture.runtime_policy.chmod(0o400)
        binding = {"docker": docker, "image_id": image["Id"], "digest": digest, "new_reference": reference, "fail_live": False}
        (fixture.root / "native-binding.json").write_text(json.dumps(binding))
        (fixture.root / "native-mapping.json").write_text(json.dumps({initial: fixture.policy["initial_image"]}))
        shutil.copyfile(ROOT / "scripts/tests/fixtures/native_updater_docker.py", fixture.root / "docker-body.py")
        fixture.auth.request["image_digest"] = digest
        fixture.auth.automatic_mode(publication_run=77, config_digest=manifest["config"]["digest"])
        (fixture.root / "policy.json").chmod(0o600)
        (fixture.root / "policy.json").write_text(json.dumps(fixture.auth.policy))
        (fixture.root / "policy.json").chmod(0o400)
        api_tool = fixture.root / "github-api"
        api_tool.write_text(api_tool.read_text().replace("route=='/actions/artifacts/504/zip'", "route.startswith('/actions/artifacts/') and route.endswith('/zip') and route!='/actions/artifacts/505/zip'"))
        def stage(run_id):
            request = {**fixture.auth.request, "run_id": run_id, "image_digest": digest}
            responses = json.loads(json.dumps(fixture.auth.api))
            for key in list(responses):
                if key.startswith("/actions/runs/501"):
                    value = responses.pop(key)
                    if key == "/actions/runs/501":
                        value["id"] = run_id
                    for job in value.get("jobs", []) if isinstance(value, dict) else []:
                        job["run_id"] = run_id
                    responses[key.replace("/actions/runs/501", f"/actions/runs/{run_id}", 1)] = value
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, "w") as archive:
                entry = zipfile.ZipInfo("request.json")
                entry.external_attr = (stat.S_IFREG | 0o600) << 16
                archive.writestr(entry, json.dumps(request))
            content = raw.getvalue()
            (fixture.root / "artifact.zip").write_bytes(content)
            artifact = json.loads(json.dumps(fixture.auth.artifact))
            artifact["workflow_run"]["id"] = run_id
            artifact["name"] = f"game-deployment-request-{run_id}-1"
            artifact.update(id=run_id + 3, digest="sha256:" + hashlib.sha256(content).hexdigest(), size_in_bytes=len(content))
            responses[f"/actions/runs/{run_id}/artifacts?per_page=100"] = {"total_count": 1, "artifacts": [artifact]}
            (fixture.root / "responses.json").write_text(json.dumps(responses))
            return {**fixture.auth.envelope, "run_id": run_id}
        def invoke(envelope, peer_uid=10002):
            path = base / "worker.sock"
            if path.exists():
                path.unlink()
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(path))
                os.chown(path, 0, 10002)
                path.chmod(0o660)
                server.listen(1)
                server.settimeout(10)
                with subprocess.Popen(["setpriv", "--reuid=" + str(peer_uid), "--regid=" + str(peer_uid), "--clear-groups", "/usr/bin/python3", str(helpers / "game_ssh_dispatch.py"), "--socket", str(path)], env={"PATH": "/usr/bin:/bin", "SSH_ORIGINAL_COMMAND": "rngwars-game-deploy-v1"}, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as client:
                    client.stdin.write(json.dumps(envelope).encode())
                    client.stdin.close()
                    client.stdin = None
                    connection, _ = server.accept()
                    with connection, subprocess.Popen(["setpriv", "--no-new-privs", "/usr/bin/python3", str(helpers / "game_updater.py"), "serve", "--policy", str(fixture.runtime_policy)], env=fixture.environment, stdin=connection, stdout=connection, stderr=subprocess.PIPE) as worker:
                        worker.wait(timeout=920)
                        connection.shutdown(socket.SHUT_WR)
                        output, error = client.communicate(timeout=15)
                        diagnostic = worker.stderr.read()
                        failure = fixture.root / "state" / ("attempt-" + str(envelope["run_id"])) / "failure.json"
                        record = json.loads(failure.read_text()) if failure.exists() else {}
                        match = re.search(rb"Game updater blocked: ([a-z_]+)", diagnostic)
                        report = {"fixture_run": envelope["run_id"], "peer_uid": peer_uid, "client_exit": client.returncode, "worker_exit": worker.returncode, "stage": record.get("stage"), "error_class": record.get("error_class"), "code": record.get("code") or (match.group(1).decode() if match else None)}
                        print(json.dumps(report), flush=True)
                        (Path(os.environ["RUNNER_TEMP"]) / "native-updater-diagnostic.json").write_text(json.dumps(report, indent=2))
                        return client.returncode, output, diagnostic
        before = json.loads(run([*user, "/usr/bin/python3", str(helpers / "game_recovery.py"), "inspect", str(database)]))
        fixture.executable("systemctl", "import datetime,sys\nprint('active' if '--property=ActiveState' in sys.argv else (datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=1)).strftime('%a %Y-%m-%d %H:%M:%S UTC'))\n")
        code, output, error = invoke(stage(501))
        assert code == 75 and json.loads(output)["status"] == "deployment_deferred", "native_deferral_failed"
        assert not (fixture.root / "state/attempt-501").exists() and not (fixture.root / "state/inflight.json").exists()
        assert before == json.loads(run([*user, "/usr/bin/python3", str(helpers / "game_recovery.py"), "inspect", str(database)]))
        fixture.executable("systemctl", "import datetime,sys\nprint('inactive' if '--property=ActiveState' in sys.argv else (datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=1)).strftime('%a %Y-%m-%d %H:%M:%S UTC'))\n")
        code, output, error = invoke(stage(501))
        assert code == 0 and json.loads(output)["status"] == "game_deployed", "native_update_failed"
        after = json.loads(run([*user, "/usr/bin/python3", str(helpers / "game_recovery.py"), "inspect", str(database)]))
        assert before == after
        current = json.loads((fixture.root / "state/current.json").read_text())
        config = 'silent\nshow-error\nfail\nurl = "http://127.0.0.1:5000/api/users/me"\nheader = ' + json.dumps("Authorization: Bearer " + token) + '\n'
        profile = json.loads(run([docker, "exec", "-i", current["container_id"], "curl", "-q", "--config", "-"], input=config.encode()))
        assert profile["id"] == user_id
        before_rollback = json.loads(run([*user, "/usr/bin/python3", str(helpers / "game_recovery.py"), "inspect", str(database)]))
        code, _, _ = invoke(stage(601), peer_uid=0)
        assert code != 0 and not (fixture.root / "state/attempt-601").exists()
        binding["fail_live"] = True
        (fixture.root / "native-binding.json").write_text(json.dumps(binding))
        code, output, _ = invoke(stage(601))
        assert code != 0 and json.loads(output)["status"] == "game_rolled_back", "native_rollback_failed"
        assert json.loads((fixture.root / "state/current.json").read_text()) == current
        assert json.loads(run([*user, "/usr/bin/python3", str(helpers / "game_recovery.py"), "inspect", str(database)]))["content"] == before_rollback["content"]
        result = {"automatic_policy_contract_exercised": True, "backup_deferral_did_not_consume_attempt": True, "native_container_update": True, "native_captured_container_rollback": True, "real_encrypted_local_restore": True, "database_identity_and_content_preserved": True, "authenticated_profile_survived_update": True, "real_private_socket_peer_checked": True, "SSH_adapter_kept_unprivileged": True, "sandboxed_database_identity_drop_verified": True, "provider_and_registry_transports_are_synthetic": True, "live_authority_or_release_cryptography_not_claimed": True}
        destination = Path(os.environ["RUNNER_TEMP"]) / "native-updater-result.json"
        destination.write_text(json.dumps(result, indent=2))
        destination.chmod(0o644)
        print(json.dumps(result))
    finally:
        mapping = fixture.root / "native-mapping.json"
        if mapping.exists():
            created.extend(json.loads(mapping.read_text()).keys())
        for identifier in set(created):
            value = subprocess.run([docker, "inspect", identifier], capture_output=True)
            if value.returncode == 0 and json.loads(value.stdout)[0]["Config"]["Labels"].get("info.rngwars.owner") == "fixture-controller":
                subprocess.run([docker, "rm", "-f", identifier], capture_output=True)
        if network:
            subprocess.run([docker, "network", "rm", network], capture_output=True)
        shutil.rmtree(base)
        fixture.doCleanups()


if __name__ == "__main__":
    main()
