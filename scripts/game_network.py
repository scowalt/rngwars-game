import argparse
import datetime
import ipaddress
import json
import os
from pathlib import Path
import re
import resource
import secrets
import select
import shlex
import signal
import shutil
import stat
import subprocess
import sys
import time

import marketing_artifact as metadata
from marketing_artifact import Blocked, require, unique_object
from marketing_producer import identifier


REPOSITORY = "scowalt/rngwars-game"
WORKFLOW = REPOSITORY + "/.github/workflows/game-deployment.yml@refs/heads/main"


def configuration():
    environment = metadata.github("/environments/game-production")
    require(environment["name"] == "game-production" and environment["can_admins_bypass"] is False and environment["deployment_branch_policy"] == {"protected_branches": False, "custom_branch_policies": True}, "private_environment_policy")
    reviewers = [rule for rule in environment["protection_rules"] if rule["type"] == "required_reviewers"]
    require(len(reviewers) == 1 and reviewers[0]["prevent_self_review"] is False and [(item["type"], item["reviewer"]["id"]) for item in reviewers[0]["reviewers"]] == [("User", 1100550)], "private_environment_reviewer")
    branches = metadata.github("/environments/game-production/deployment-branch-policies")
    require(branches["total_count"] == len(branches["branch_policies"]) == 1 and [(item["name"], item["type"]) for item in branches["branch_policies"]] == [("main", "branch")], "private_environment_branch")
    return environment


def resolve(env):
    require(env.get("GITHUB_ACTIONS") == "true" and env.get("GITHUB_REPOSITORY") == REPOSITORY and env.get("GITHUB_REPOSITORY_ID") == "1442331254" and env.get("GITHUB_REPOSITORY_OWNER_ID") == "1100550", "private_repository_context")
    require(env.get("GITHUB_REF") == "refs/heads/main" and env.get("GITHUB_WORKFLOW_REF") == WORKFLOW and env.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and env.get("GITHUB_RUN_ATTEMPT") == "1" and env.get("RUNNER_ENVIRONMENT") == "github-hosted", "private_workflow_context")
    require(env.get("GITHUB_ACTOR") == env.get("GITHUB_TRIGGERING_ACTOR") == "scowalt" and env.get("GITHUB_ACTOR_ID") == "1100550", "private_actor")
    revision = env.get("GITHUB_SHA", "")
    require(re.fullmatch(r"[a-f0-9]{40}", revision) and env.get("GITHUB_WORKFLOW_SHA") == env.get("APPROVED_REVISION") == revision, "private_controller_revision")
    operation = env.get("GAME_PREFLIGHT_OPERATION")
    require(operation in {"verify-release", "private-preflight", "deploy"}, "private_operation")
    if operation in {"private-preflight", "deploy"}:
        flag = "GAME_DEPLOYMENT_ENABLED" if operation == "deploy" else "GAME_PRIVATE_PREFLIGHT_ENABLED"
        require(env.get(flag) == "true", "private_operation_disabled")
        configuration()
    run_id = identifier(env.get("GITHUB_RUN_ID", ""))
    ci_run = identifier(env.get("SOURCE_CI_RUN_ID", ""))
    identity = metadata.resolve_ci(ci_run, revision)
    require(identity["source_revision"] == revision and identity["source_branch"] == "main", "private_main_CI")
    ci = metadata.github(f"/actions/runs/{ci_run}")
    created = datetime.datetime.fromisoformat(ci["created_at"])
    require(created.tzinfo is not None and -300 <= (datetime.datetime.now(datetime.timezone.utc) - created).total_seconds() <= 86400, "private_CI_freshness")
    workflow = metadata.github("/actions/workflows/game-deployment.yml")
    run = metadata.github(f"/actions/runs/{run_id}")
    require(workflow["state"] == "active" and workflow["path"] == run["path"] == ".github/workflows/game-deployment.yml" and run["workflow_id"] == workflow["id"] and run["id"] == run_id, "private_workflow_identity")
    require(run["repository"]["id"] == run["head_repository"]["id"] == 1442331254 and run["head_sha"] == revision and run["head_branch"] == "main" and run["actor"]["id"] == run["triggering_actor"]["id"] == 1100550 and run["event"] == "workflow_dispatch" and type(run["run_attempt"]) is int and run["run_attempt"] == 1 and run["status"] == "in_progress", "private_run_identity")
    return {"status": "private_preflight_context_only", "controller_revision": revision, "run_id": run_id, "ci_run_id": ci_run}


def private_authority(env):
    operation = env.get("GAME_PREFLIGHT_OPERATION")
    require(operation in {"private-preflight", "deploy"} and env.get("GITHUB_JOB") == ("deploy" if operation == "deploy" else "preflight"), "private_probe_not_selected")
    identity = resolve(env)
    environment = configuration()
    reviews = metadata.github(f"/actions/runs/{identity['run_id']}/approvals")
    selected = [review for review in reviews if any(item["id"] == environment["id"] and item["name"] == "game-production" for item in review["environments"])]
    require(len(selected) == 1 and selected[0]["state"] == "approved" and selected[0]["user"]["id"] == 1100550, "private_review_missing")
    inventory = metadata.github(f"/actions/runs/{identity['run_id']}/attempts/1/jobs?per_page=100")
    require(inventory["total_count"] == len(inventory["jobs"]) == 3 and {job["name"] for job in inventory["jobs"]} == {"resolve", "Private transport preflight", "Deploy verified game release"}, "private_job_inventory")
    selected_name = "Deploy verified game release" if operation == "deploy" else "Private transport preflight"
    jobs = [job for job in inventory["jobs"] if job["name"] == selected_name]
    require(len(jobs) == 1 and jobs[0]["run_id"] == identity["run_id"] and jobs[0]["status"] == "in_progress" and jobs[0]["labels"] == ["ubuntu-24.04"], "private_job_runner")
    return identity


def deployment_request(env):
    require(env.get("GITHUB_JOB") == "resolve" and env.get("GAME_PREFLIGHT_OPERATION") == "deploy", "private_request_not_selected")
    context = resolve(env)
    source = env.get("IMAGE_SOURCE_REVISION", "")
    digest = env.get("EXPECTED_IMAGE_DIGEST", "")
    require(re.fullmatch(r"[a-f0-9]{40}", source) and re.fullmatch(r"sha256:[a-f0-9]{64}", digest), "private_request_image")
    return {"version": 1, "operation": "deploy", "run_id": context["run_id"], "controller_revision": context["controller_revision"], "ci_run_id": context["ci_run_id"], "image_source_revision": source, "image_digest": digest, "publication_run_id": identifier(env.get("PUBLICATION_RUN_ID", ""))}


def binding(env):
    raw = env.get("GAME_NETWORK_BINDING", "")
    require(0 < len(raw) <= 8192, "private_binding_missing")
    value = json.loads(raw, object_pairs_hook=unique_object)
    require(type(value) is dict and set(value) == {"client_id", "audience", "target_ipv4", "target_port", "ssh_user", "host_public_key", "denied_probe_ipv4"}, "private_binding_shape")
    require(type(value["client_id"]) is str and re.fullmatch(r"[A-Za-z0-9_-]{8,200}", value["client_id"]) and not value["client_id"].startswith("tskey-") and value["audience"] == "api.tailscale.com/" + value["client_id"], "private_OIDC_binding")
    network = ipaddress.ip_network("100.64.0.0/10")
    require(all(type(value[name]) is str and ipaddress.ip_address(value[name]) in network for name in ["target_ipv4", "denied_probe_ipv4"]) and value["target_ipv4"] != value["denied_probe_ipv4"], "private_target_address")
    require(type(value["target_port"]) is int and 1024 <= value["target_port"] <= 65535 and value["ssh_user"] == "rngwars-deploy", "private_target_port_or_user")
    require(type(value["host_public_key"]) is str and re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/]{40,200}={0,2}", value["host_public_key"]), "private_host_key")
    credential = env.get("GAME_SSH_PRIVATE_KEY", "")
    key_kind = "OPENSSH PRIVATE KEY"
    require(80 <= len(credential) <= 16384 and credential.startswith("-----BEGIN " + key_kind + "-----\n") and credential.rstrip().endswith("-----END " + key_kind + "-----"), "private_SSH_key_missing")
    return value, credential


def state_path(env):
    run_id = identifier(env.get("GITHUB_RUN_ID", ""))
    require(env.get("GITHUB_RUN_ATTEMPT") == "1", "private_attempt")
    parent = Path(env["RUNNER_TEMP"])
    require(parent.is_absolute() and parent.is_dir() and not any(part.is_symlink() for part in (parent, *parent.parents)) and parent.stat().st_uid == os.geteuid(), "private_temporary_parent")
    return parent / f"rngwars-game-network-{run_id}-1"


def plain_environment(env, directory):
    return {"PATH": env.get("PATH", os.defpath), "HOME": str(directory)}


def probe(env):
    identity = private_authority(env)
    settings, credential = binding(env)
    require(env.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN") and env.get("ACTIONS_ID_TOKEN_REQUEST_URL", "").startswith("https://"), "private_OIDC_runtime_missing")
    root = state_path(env)
    require(not root.exists() and not root.is_symlink(), "private_state_already_exists")
    root.mkdir(mode=0o700)
    environment = plain_environment(env, root)
    socket = root / "tailscaled.sock"
    client = ["tailscale", "--socket=" + str(socket)]
    process = None
    log = None
    logout_ok = True
    try:
        with (root / "owner.json").open("x") as stream:
            json.dump({"run_id": identity["run_id"], "revision": identity["controller_revision"]}, stream)
        with (root / "key").open("x") as stream:
            stream.write(credential.rstrip() + "\n")
        (root / "key").chmod(0o600)
        with (root / "known_hosts").open("x") as stream:
            stream.write("rngwars-game-deployment " + settings["host_public_key"] + "\n")
        log = (root / "daemon.log").open("xb")
        process = subprocess.Popen(["tailscaled", "--tun=userspace-networking", "--socket=" + str(socket), "--state=mem:", "--port=0"], env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        with (root / "process.json").open("x") as stream:
            json.dump({"pid": process.pid, "start": Path(f"/proc/{process.pid}/stat").read_text().rpartition(")")[2].split()[19]}, stream)
        deadline = time.monotonic() + 10
        while not socket.exists():
            require(process.poll() is None and time.monotonic() < deadline, "private_daemon_unavailable")
            time.sleep(0.05)
        require(stat.S_ISSOCK(socket.lstat().st_mode), "private_daemon_socket")
        oidc_environment = {**environment, **{key: env[key] for key in ["GITHUB_ACTIONS", "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL"]}}
        joined = subprocess.run([*client, "up", "--client-id=" + settings["client_id"] + "?ephemeral=true&preauthorized=true", "--audience=" + settings["audience"], "--advertise-tags=tag:rngwars-game-ci", "--hostname=rngwars-game-ci-" + str(identity["run_id"]), "--accept-dns=false", "--accept-routes=false", "--ssh=false", "--shields-up=true", "--timeout=60s"], env=oidc_environment, capture_output=True, timeout=70)
        require(joined.returncode == 0, "private_OIDC_join_failed")
        status = subprocess.run([*client, "status", "--json"], env=environment, capture_output=True, timeout=15)
        require(status.returncode == 0 and len(status.stdout) <= 2 * 1024 * 1024, "private_node_status")
        node = json.loads(status.stdout, object_pairs_hook=unique_object)
        require(node["BackendState"] == "Running" and node["Self"]["Tags"] == ["tag:rngwars-game-ci"], "private_node_identity")
        require(metadata.github("/git/ref/heads/main")["object"]["sha"] == identity["controller_revision"], "private_stale_controller")
        binary = shutil.which("tailscale", path=environment["PATH"])
        require(binary is not None, "private_client_unavailable")
        proxy = shlex.join([binary, "--socket=" + str(socket), "nc", "%h", "%p"])
        challenge = secrets.token_hex(32)
        request = json.dumps({"version": 1, "challenge": challenge}).encode()
        command = ["ssh", "-F", "/dev/null", "-T", "-i", str(root / "key"), "-p", str(settings["target_port"]), "-o", "BatchMode=yes", "-o", "ConnectionAttempts=1", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + str(root / "known_hosts"), "-o", "GlobalKnownHostsFile=/dev/null", "-o", "HostKeyAlias=rngwars-game-deployment", "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none", "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes", "-o", "PermitLocalCommand=no", "-o", "ProxyCommand=" + proxy, settings["ssh_user"] + "@" + settings["target_ipv4"], "rngwars-game-preflight-v1"]
        result = subprocess.run(command, env=environment, input=request, capture_output=True, timeout=30)
        require(result.returncode == 0 and len(result.stdout) <= 1024, "private_SSH_probe_failed")
        require(json.loads(result.stdout, object_pairs_hook=unique_object) == {"version": 1, "challenge": challenge, "status": "restricted_transport_only"}, "private_probe_reply")
        for host, port in [(settings["target_ipv4"], 22), (settings["target_ipv4"], 443), (settings["denied_probe_ipv4"], 22)]:
            try:
                denied = subprocess.run([*client, "nc", host, str(port)], env=environment, input=b"", capture_output=True, timeout=5)
                require(denied.returncode != 0 and not denied.stdout, "private_negative_route_connected")
            except subprocess.TimeoutExpired:
                pass
        if env.get("GAME_PREFLIGHT_OPERATION") == "deploy":
            private_authority(env)
            require(env.get("GH_TOKEN"), "private_job_token_missing")
            envelope = json.dumps({"version": 1, "run_id": identity["run_id"], "github_token": env["GH_TOKEN"]}).encode()
            deployed = subprocess.run([*command[:-1], "rngwars-game-deploy-v1"], env=environment, input=envelope, capture_output=True, timeout=920)
            require(deployed.returncode in {0, 1} and 0 < len(deployed.stdout) <= 4096, "private_deployment_outcome_unconfirmed")
            reply = json.loads(deployed.stdout, object_pairs_hook=unique_object)
            require(type(reply) is dict and set(reply) == {"status", "run_id", "controller_revision", "image_digest", "source_revision", "publication_run_id"} and reply["run_id"] == identity["run_id"] and reply["controller_revision"] == identity["controller_revision"] and reply["image_digest"] == env["EXPECTED_IMAGE_DIGEST"] and reply["source_revision"] == env["IMAGE_SOURCE_REVISION"] and reply["publication_run_id"] == identifier(env["PUBLICATION_RUN_ID"]), "private_deployment_reply")
            require((deployed.returncode == 0 and reply["status"] == "game_deployed") or (deployed.returncode == 1 and reply["status"] in {"game_rolled_back", "deployment_blocked_before_live_change", "operator_recovery_required"}), "private_deployment_reply")
            return reply
        return {**identity, "status": "private_transport_verified_no_deployment", "negative_connection_checks": 3, "probe_protocol": 1}
    finally:
        if process is not None:
            try:
                if process.poll() is None and socket.exists():
                    logout = subprocess.run([*client, "logout"], env=environment, capture_output=True, timeout=15)
                    logout_ok = logout.returncode == 0
            except Exception:
                logout_ok = False
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
        if log is not None:
            log.close()
        shutil.rmtree(root)
        require(logout_ok, "private_logout_unconfirmed")


def owned_record(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600 and 0 < info.st_size <= 4096, "private_cleanup_record")
    return json.loads(path.read_bytes(), object_pairs_hook=unique_object)


def cleanup(env):
    root = state_path(env)
    if not root.exists() and not root.is_symlink():
        return {"status": "owned_private_state_absent"}
    info = root.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700, "private_cleanup_directory")
    owner = owned_record(root / "owner.json")
    require(owner == {"run_id": identifier(env["GITHUB_RUN_ID"]), "revision": env["GITHUB_SHA"]} and env.get("GITHUB_WORKFLOW_SHA") == env["GITHUB_SHA"] and env.get("GITHUB_REPOSITORY") == REPOSITORY and env.get("GITHUB_WORKFLOW_REF") == WORKFLOW, "private_cleanup_owner")
    socket = root / "tailscaled.sock"
    logout_ok = True
    if (root / "process.json").exists():
        process = owned_record(root / "process.json")
        require(set(process) == {"pid", "start"} and type(process["pid"]) is int and process["pid"] > 1 and process["pid"] != os.getpid() and type(process["start"]) is str and process["start"].isdigit(), "private_cleanup_process")
        try:
            descriptor = os.pidfd_open(process["pid"])
        except ProcessLookupError:
            descriptor = None
        if descriptor is not None:
            try:
                path = Path("/proc") / str(process["pid"])
                require(path.stat().st_uid == os.geteuid() and path.joinpath("stat").read_text().rpartition(")")[2].split()[19] == process["start"], "private_cleanup_process_changed")
                arguments = path.joinpath("cmdline").read_bytes().split(b"\x00")
                require(("--socket=" + str(socket)).encode() in arguments and b"--state=mem:" in arguments and b"--tun=userspace-networking" in arguments, "private_cleanup_process_arguments")
                if socket.exists():
                    try:
                        result = subprocess.run(["tailscale", "--socket=" + str(socket), "logout"], env=plain_environment(env, root), capture_output=True, timeout=15)
                        logout_ok = result.returncode == 0
                    except Exception:
                        logout_ok = False
                monitor = select.poll()
                monitor.register(descriptor, select.POLLIN)
                signal.pidfd_send_signal(descriptor, signal.SIGTERM)
                if not monitor.poll(5000):
                    signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                    require(bool(monitor.poll(5000)), "private_cleanup_process_alive")
            finally:
                os.close(descriptor)
    else:
        require(not socket.exists(), "private_cleanup_process_missing")
    shutil.rmtree(root)
    require(logout_ok, "private_cleanup_logout_unconfirmed")
    return {"status": "owned_private_state_cleaned"}


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["resolve", "probe", "deploy", "request", "cleanup"])
    args = parser.parse_args()
    try:
        require(args.operation != "deploy" or os.environ.get("GAME_PREFLIGHT_OPERATION") == "deploy", "private_deploy_not_selected")
        require(args.operation != "probe" or os.environ.get("GAME_PREFLIGHT_OPERATION") == "private-preflight", "private_probe_not_selected")
        action = {"resolve": resolve, "probe": probe, "deploy": probe, "request": deployment_request, "cleanup": cleanup}[args.operation]
        result = action(os.environ)
        print(json.dumps(result, sort_keys=True))
        return 1 if args.operation == "deploy" and result["status"] != "game_deployed" else 0
    except Blocked as error:
        print("Game private preflight blocked: " + str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Game private preflight blocked: invalid_or_unavailable_evidence", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
