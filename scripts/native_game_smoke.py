import argparse
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time
import uuid


class Failed(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise Failed(code)


def validate_context(env, machine):
    require(env.get("GITHUB_ACTIONS") == "true" and env.get("GITHUB_REPOSITORY_ID") == "1442331254" and env.get("RUNNER_ARCH") == "ARM64" and machine == "aarch64", "native_hosted_ARM_required")
    require(re.fullmatch(r"[a-f0-9]{40}", env.get("GITHUB_SHA", "")), "exact_source_required")


def command(args, content=None, timeout=45, required=True, env=None):
    result = subprocess.run(args, input=content, capture_output=True, text=True, timeout=timeout, env=env)
    if required:
        require(result.returncode == 0, "synthetic_fixture_command_failed")
    return result


def encrypted_roundtrip(source, root):
    require(root.is_absolute() and not root.is_symlink() and root.stat().st_mode & 0o777 == 0o700, "private_fixture_directory_required")
    state = root / "state"
    state.mkdir(mode=0o700)
    password = root / "password"
    with password.open("x") as handle:
        password.chmod(0o600)
        handle.write("synthetic-local-fixture-only\n")
    repository = root / "repository"
    policy = root / "policy.json"
    with policy.open("x") as handle:
        policy.chmod(0o600)
        json.dump({"repository": str(repository), "host": "native-fixture", "tag": "fresh-baseline", "image_repository": "ghcr.io/example/game", "data_directory": str(root)}, handle)
    env = {"PATH": os.environ["PATH"], "RESTIC_REPOSITORY": str(repository), "RESTIC_PASSWORD_FILE": str(password), "SQLITE_BACKUP_STATE_DIR": str(state), "SQLITE_BACKUP_POLICY_FILE": str(policy), "TZ": "UTC"}
    operator = [sys.executable, str(Path(__file__).with_name("sqlite-backup.py"))]
    command(operator + ["init"], env=env, timeout=120)
    backup = command(operator + ["backup", str(source)], env=env, timeout=120)
    snapshot = backup.stdout.strip().split()[-1]
    require(re.fullmatch(r"[a-f0-9]{64}", snapshot), "fixture_snapshot_identity")
    restored = root / "restored.db"
    command(operator + ["restore", snapshot, str(restored)], env=env, timeout=120)
    command(operator + ["verify", str(source), str(restored)], env=env)
    command(operator + ["check"], env=env, timeout=120)
    return restored


def request(container, method, path, token=None, body=None):
    require(re.fullmatch(r"/api/[a-zA-Z0-9/_-]+|/", path), "fixture_endpoint")
    config = ["silent", "show-error", "max-time = 3", "url = " + json.dumps("http://127.0.0.1:5000" + path), "request = " + json.dumps(method), 'write-out = "\\n%{http_code}"']
    if token:
        uuid.UUID(token)
        config.append("header = " + json.dumps("Authorization: Bearer " + token))
    if body is not None:
        config.extend(['header = "Content-Type: application/json"', "data = " + json.dumps(json.dumps(body))])
    result = command(["docker", "exec", "-i", container, "curl", "--config", "-"], "\n".join(config) + "\n", required=False)
    if result.returncode != 0:
        return 0, None
    content, _, status = result.stdout.rpartition("\n")
    require(status.isdigit(), "fixture_http_status")
    try:
        return int(status), json.loads(content)
    except ValueError:
        return int(status), content


def ready(container):
    for attempt in range(40):
        status, body = request(container, "GET", "/api/health")
        if status == 200 and isinstance(body, dict) and body.get("status") == "ok":
            return
        running = command(["docker", "inspect", "--format", "{{.State.Running}}", container], required=False)
        if running.stdout.strip() == "false":
            break
        time.sleep(1)
    raise Failed("synthetic_service_not_healthy")


def main():
    validate_context(os.environ, platform.machine())
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    args = parser.parse_args()
    require(args.image == "rngwars-native:" + os.environ["GITHUB_SHA"], "fixture_image_binding")
    image = json.loads(command(["docker", "image", "inspect", args.image]).stdout)[0]
    require(image["Architecture"] == "arm64" and image["Os"] == "linux" and image["Config"]["User"] == "10001:10001", "native_image_identity")
    require(image["Config"]["Entrypoint"] == ["/app/game-entrypoint.sh"] and image["Config"]["Cmd"] == ["dotnet", "RNGWars.Api.dll"], "runtime_command_changed")
    prefix = "rngwars-native-" + uuid.uuid4().hex
    volume = prefix + "-data"
    containers = []
    created = False
    checks = []
    try:
        command(["docker", "volume", "create", "--label", "rngwars.synthetic=true", volume])
        created = True
        command(["docker", "run", "--rm", "--network", "none", "--read-only", "--user", "0:0", "--entrypoint", "/bin/sh", "--mount", f"type=volume,src={volume},dst=/data", args.image, "-c", "chown 10001:10001 /data && chmod 0700 /data"])
        runtime = ["--network", "none", "--read-only", "--ulimit", "core=0", "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--mount", f"type=volume,src={volume},dst=/data"]
        def initialize(label, database, root=False):
            name = prefix + "-" + label
            containers.append(name)
            user = ["--user", "0:0"] if root else []
            result = command(["docker", "run", "--init", "--name", name, *runtime, *user, "-e", "DOTNET_URLS=invalid-listening-address", "-e", "DOTNET_ENVIRONMENT=Production", "-e", "ASPNETCORE_ENVIRONMENT=Production", "-e", "DATABASE_PATH=:memory:", "-e", "SENTRY_DSN=", args.image, "dotnet", "RNGWars.Api.dll", "init-db", database], required=False)
            if root:
                require(result.returncode == 1 and "Database initialization failed;" in result.stderr, "root_initialization_not_rejected")
            else:
                require(result.returncode == 0 and "Database initialized" in result.stdout and "Application started" not in result.stdout, "offline_initialization_failed")
            return name
        def start(label, environment, database="/data/restored.db"):
            name = prefix + "-" + label
            containers.append(name)
            command(["docker", "run", "-d", "--init", "--name", name, *runtime, "-e", "DOTNET_URLS=http://127.0.0.1:5000", "-e", "DOTNET_ENVIRONMENT=" + environment, "-e", "ASPNETCORE_ENVIRONMENT=" + environment, "-e", "DATABASE_PATH=" + database, "-e", "SENTRY_DSN=", args.image])
            return name
        seed = start("empty-schema", "Testing", "/data/unmarked.db")
        ready(seed)
        command(["docker", "stop", "--time", "10", seed])
        empty = start("refuse-empty", "Production", "/data/unmarked.db")
        result = command(["docker", "wait", empty], timeout=40)
        require(result.stdout.strip().isdigit() and int(result.stdout.strip()) != 0, "empty_production_database_accepted")
        checks.append("production_rejects_unmarked_empty_population")
        initialize("refuse-root-init", "/data/root-rejected.db", root=True)
        initialized = initialize("offline-init", "/data/game.db")
        with tempfile.TemporaryDirectory(prefix="rngwars-native-backup-") as area:
            root = Path(area)
            source = root / "initialized.db"
            command(["docker", "cp", initialized + ":/data/game.db", str(source)])
            source.chmod(0o600)
            restored = encrypted_roundtrip(source, root)
            command(["docker", "run", "--rm", *runtime, "--entrypoint", "/bin/sh", args.image, "-c", "test ! -e /data/restored.db && test ! -e /data/root-rejected.db"])
            command(["docker", "cp", str(restored), initialized + ":/data/restored.db"])
            command(["docker", "run", "--rm", *runtime, "--user", "0:0", "--entrypoint", "/bin/sh", args.image, "-c", "chown 10001:10001 /data/restored.db && chmod 0600 /data/restored.db"])
        checks.extend(["offline_initialization_without_web_host", "offline_initialization_rejects_root", "encrypted_empty_baseline_backup_restore"])
        seed = start("first-production", "Production")
        ready(seed)
        status, leaderboard = request(seed, "GET", "/api/leaderboard")
        require(status == 200 and isinstance(leaderboard, dict) and leaderboard.get("entries") == [] and leaderboard.get("hasMore") is False, "fresh_baseline_not_empty")
        checks.append("production_accepts_initialized_empty_restore")
        status, signup = request(seed, "POST", "/api/users/anonymous", body={})
        require(status == 201 and isinstance(signup, dict), "native_signup_failed")
        token = signup["token"]
        user_id = signup["user"]["id"]
        uuid.UUID(token)
        status, profile = request(seed, "PUT", "/api/users/me", token, {"username": "NativeArmFixture"})
        require(status == 200 and profile["username"] == "NativeArmFixture", "native_profile_update_failed")
        status, match = request(seed, "POST", "/api/matches/practice", token, {})
        require(status == 201 and isinstance(match.get("matchId"), str), "native_practice_creation_failed")
        checks.extend(["native_SQLite_signup", "profile_update", "practice_creation"])
        command(["docker", "stop", "--time", "10", seed])
        production = start("production", "Production")
        ready(production)
        host = json.loads(command(["docker", "inspect", production]).stdout)[0]["HostConfig"]
        require(host["Init"] is True and host["NetworkMode"] == "none" and not host["PortBindings"], "fixture_container_isolation")
        status, profile = request(production, "GET", "/api/users/me", token)
        require(status == 200 and profile["id"] == user_id and profile["username"] == "NativeArmFixture", "persistent_token_roundtrip_failed")
        status, page = request(production, "GET", "/")
        require(status == 200 and isinstance(page, str) and "<html" in page.lower(), "bundled_frontend_unavailable")
        command(["docker", "exec", production, "/bin/sh", "-c", "test -s /usr/share/doc/rngwars/LICENSE && test -s /usr/share/doc/rngwars/THIRD_PARTY_LICENSES.txt"])
        checks.extend(["production_restart_with_same_DB_and_token", "bundled_frontend", "distributed_legal_notices"])
        command(["docker", "stop", "--time", "10", production])
        missing = start("refuse-missing", "Production", "/data/missing.db")
        result = command(["docker", "wait", missing], timeout=40)
        require(result.stdout.strip().isdigit() and int(result.stdout.strip()) != 0, "missing_production_database_accepted")
        command(["docker", "run", "--rm", "--network", "none", "--read-only", "--entrypoint", "/bin/sh", "--mount", f"type=volume,src={volume},dst=/data", args.image, "-c", "test ! -e /data/missing.db"])
        checks.append("production_does_not_create_missing_DB")
        result = {"source_revision": os.environ["GITHUB_SHA"], "image_id": image["Id"], "native_runner_architecture": platform.machine(), "image_architecture": image["Architecture"], "container_init": host["Init"], "checks": checks, "synthetic_data_only": True, "published_host_ports": False, "external_container_network": False, "production_host_access": False}
        path = Path(os.environ["RUNNER_TEMP"]) / "native-game-result.json"
        with path.open("x") as handle:
            json.dump(result, handle, indent=2)
            handle.write("\n")
        print(json.dumps({"native_runtime_verified": True, "synthetic_checks": len(checks), "source_revision": result["source_revision"]}))
    except Exception:
        for name in containers:
            logs = command(["docker", "logs", "--tail", "40", name], required=False)
            text = (logs.stdout + logs.stderr)[-6000:]
            text = re.sub(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", "<synthetic-id>", text)
            print("Isolated synthetic fixture diagnostics: " + text)
        raise
    finally:
        for name in reversed(containers):
            command(["docker", "rm", "-f", name], required=False)
        if created:
            command(["docker", "volume", "rm", volume])


if __name__ == "__main__":
    try:
        main()
    except Failed as error:
        print("Native game validation failed: " + str(error))
        raise SystemExit(1)
    except Exception as error:
        print("Native game validation failed: " + type(error).__name__ + "; synthetic identity/log values withheld")
        raise SystemExit(1)
