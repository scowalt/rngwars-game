import argparse
import json
import os
from pathlib import Path
import platform
import re
import subprocess
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


def command(args, content=None, timeout=45, required=True):
    result = subprocess.run(args, input=content, capture_output=True, text=True, timeout=timeout)
    if required:
        require(result.returncode == 0, "owned_container_command_failed")
    return result


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
        def start(label, environment, database="/data/game.db"):
            name = prefix + "-" + label
            containers.append(name)
            command(["docker", "run", "-d", "--name", name, "--network", "none", "--read-only", "--ulimit", "core=0", "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--mount", f"type=volume,src={volume},dst=/data", "-e", "DOTNET_URLS=http://127.0.0.1:5000", "-e", "DOTNET_ENVIRONMENT=" + environment, "-e", "ASPNETCORE_ENVIRONMENT=" + environment, "-e", "DATABASE_PATH=" + database, "-e", "SENTRY_DSN=", args.image])
            return name
        seed = start("empty-schema", "Testing")
        ready(seed)
        command(["docker", "stop", "--time", "10", seed])
        empty = start("refuse-empty", "Production")
        result = command(["docker", "wait", empty], timeout=40)
        require(result.stdout.strip().isdigit() and int(result.stdout.strip()) != 0, "empty_production_database_accepted")
        checks.append("production_rejects_empty_population")
        seed = start("seed", "Testing")
        ready(seed)
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
        result = {"source_revision": os.environ["GITHUB_SHA"], "image_id": image["Id"], "native_runner_architecture": platform.machine(), "image_architecture": image["Architecture"], "checks": checks, "synthetic_data_only": True, "published_host_ports": False, "external_container_network": False, "production_host_access": False}
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
    except Exception:
        print("Native game validation failed; synthetic identity/log values withheld")
        raise SystemExit(1)
