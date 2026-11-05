import argparse
import calendar
import fcntl
import json
import os
from pathlib import Path
import re
import resource
import signal
import socket
import stat
import struct
import subprocess
import sys
import time

import game_deploy_authority as authority
import game_release
from marketing_artifact import Blocked, require, unique_object


MAX_JSON = 2 * 1024 * 1024


class UncertainMutation(Blocked):
    pass


def private_path(value, uid, directory=False, readonly=False):
    path = Path(value)
    require(path.is_absolute() and ".." not in path.parts and not any(part.is_symlink() for part in (path, *path.parents)), "updater_path")
    for parent in path.parents:
        metadata = parent.stat()
        require(metadata.st_uid in {0, uid, os.geteuid()} and not metadata.st_mode & 0o022, "updater_path_ancestor")
    info = path.stat()
    require(info.st_uid == uid and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)), "updater_owner_or_type")
    require(stat.S_IMODE(info.st_mode) in ({0o400, 0o440} if readonly else {0o700} if directory else {0o600}), "updater_permissions")
    require(directory or info.st_nlink == 1, "updater_links")
    return path


def configuration(value):
    path = private_path(value, os.geteuid(), readonly=True)
    private_path(str(path.parent), os.geteuid(), directory=True)
    for parent in path.parents:
        require(parent.stat().st_uid in {0, os.geteuid()} and not parent.stat().st_mode & 0o022, "updater_policy_ancestor")
    policy = json.loads(game_release.bounded_file(str(path), 16384), object_pairs_hook=unique_object)
    fields = {"version", "host_id", "architecture", "authority_policy", "state_directory", "work_directory", "database", "data_uid", "data_gid", "data_device", "data_inode", "schema", "backup_environment", "workload", "network", "network_id", "owner_key", "owner_value", "initial_container", "initial_image", "peer_uid", "peer_gid", "health_seconds"}
    require(type(policy) is dict and set(policy) == fields and type(policy["version"]) is int and policy["version"] == 1, "updater_policy_shape")
    require(all(type(policy[k]) is int and policy[k] >= 0 for k in ["data_uid", "data_gid", "peer_uid", "peer_gid", "data_device", "data_inode", "health_seconds"]) and 1 <= policy["health_seconds"] <= 90, "updater_policy_numbers")
    require(policy["architecture"] in {"aarch64", "x86_64"} and re.fullmatch(r"[1-9][0-9]{0,19}", policy["host_id"]), "updater_host_policy")
    require(all(type(policy[k]) is str and re.fullmatch(r"[a-f0-9]{64}", policy[k]) for k in ["schema", "network_id", "initial_container"]), "updater_policy_identity")
    require(all(type(policy[k]) is str and re.fullmatch(r"[a-z][a-z0-9.-]{0,79}", policy[k]) for k in ["workload", "network", "owner_key", "owner_value"]), "updater_policy_names")
    require(re.fullmatch(re.escape(game_release.IMAGE) + r"@sha256:[a-f0-9]{64}", policy["initial_image"]), "updater_initial_image")
    authority.read_policy(policy["authority_policy"])
    private_path(policy["state_directory"], os.geteuid(), directory=True)
    private_path(policy["work_directory"], policy["data_uid"], directory=True)
    private_path(policy["database"], policy["data_uid"])
    private_path(str(Path(policy["database"]).parent), policy["data_uid"], directory=True)
    private_path(policy["backup_environment"], policy["data_uid"])
    return policy


def save(path, value, replace=False):
    destination = path.with_name(path.name + ".staging") if replace else path
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    if replace:
        os.replace(destination, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def load(path):
    private_path(str(path), os.geteuid())
    return json.loads(game_release.bounded_file(str(path)), object_pairs_hook=unique_object)


class Updater:
    def __init__(self, policy):
        self.policy = policy
        self.state = Path(policy["state_directory"])
        self.environment = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(self.state), "TZ": "UTC", "LC_ALL": "C"}
        self.docker = ["docker", "--host", "unix:///var/run/docker.sock", "--config", str(self.state / "docker-config")]

    def run(self, args, timeout=60, checked=True):
        operation = args[len(self.docker):] if args[:len(self.docker)] == self.docker else []
        mutation = bool(operation) and (operation[0] in {"create", "start", "stop", "rename"} or operation[:2] in [["network", "connect"], ["network", "disconnect"]])
        try:
            result = subprocess.run(args, env=self.environment, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            if mutation:
                raise UncertainMutation("updater_mutation_outcome_unconfirmed") from None
            raise
        if mutation and result.returncode != 0:
            raise UncertainMutation("updater_mutation_outcome_unconfirmed")
        require(len(result.stdout) <= MAX_JSON, "updater_output_size")
        require(not checked or result.returncode == 0, "updater_command_failed")
        return result

    def docker_json(self, *args):
        rows = json.loads(self.run([*self.docker, *args]).stdout, object_pairs_hook=unique_object)
        require(type(rows) is list and len(rows) == 1, "updater_docker_inventory")
        return rows[0]

    def data(self, command, *args):
        prefix = [] if os.geteuid() == self.policy["data_uid"] and os.getegid() == self.policy["data_gid"] else ["setpriv", "--reuid=" + str(self.policy["data_uid"]), "--regid=" + str(self.policy["data_gid"]), "--clear-groups", "--no-new-privs"]
        result = self.run([*prefix, sys.executable, str(Path(__file__).with_name("game_recovery.py")), command, *map(str, args)], timeout=300)
        return json.loads(result.stdout, object_pairs_hook=unique_object)

    def storage(self):
        value = self.data("inspect", self.policy["database"])
        require(value["schema"] == self.policy["schema"] and value["device"] == self.policy["data_device"] and value["inode"] == self.policy["data_inode"], "updater_storage_changed")
        return value

    def area(self, path):
        path.mkdir(mode=0o700)
        if os.geteuid() != self.policy["data_uid"] or os.getegid() != self.policy["data_gid"]:
            os.chown(path, self.policy["data_uid"], self.policy["data_gid"])
        return path

    def current(self):
        path = self.state / "current.json"
        value = load(path) if path.exists() or path.is_symlink() else {"container_id": self.policy["initial_container"], "image": self.policy["initial_image"]}
        require(set(value) == {"container_id", "image"} and re.fullmatch(r"[a-f0-9]{64}", value["container_id"]) and re.fullmatch(re.escape(game_release.IMAGE) + r"@sha256:[a-f0-9]{64}", value["image"]), "updater_current_identity")
        return value

    def container(self, identifier, image, mount, running=None, network=None):
        value = self.docker_json("inspect", identifier)
        config = value["Config"]
        host = value["HostConfig"]
        require(value["Id"] == identifier and config["Image"] == image and config["User"] == f"{self.policy['data_uid']}:{self.policy['data_gid']}" and config["Labels"].get(self.policy["owner_key"]) == self.policy["owner_value"], "updater_workload_identity")
        require(config["Entrypoint"] == ["/app/game-entrypoint.sh"] and config["Cmd"] == ["dotnet", "RNGWars.Api.dll"], "updater_workload_command")
        require(not host["PortBindings"] and host["Init"] is True and host["ReadonlyRootfs"] is True and host["Privileged"] is False and host["CapDrop"] == ["ALL"] and "no-new-privileges" in host["SecurityOpt"] and not host.get("CapAdd") and not host.get("Devices") and host.get("PidMode", "") == "" and host.get("IpcMode", "private") == "private", "updater_workload_isolation")
        require(len(value["Mounts"]) == 1 and value["Mounts"][0]["Type"] == "bind" and value["Mounts"][0]["Source"] == str(mount) and value["Mounts"][0]["Destination"] == "/data" and value["Mounts"][0]["RW"] is True, "updater_workload_storage")
        require(running is None or value["State"]["Running"] is running, "updater_workload_state")
        require(network is None or (host["NetworkMode"] == network and set(value["NetworkSettings"]["Networks"]) == {network}), "updater_workload_network")
        if network == self.policy["network"]:
            require(value["NetworkSettings"]["Networks"][network]["NetworkID"] == self.policy["network_id"], "updater_workload_network_identity")
        return value

    def healthy(self, identifier):
        deadline = time.monotonic() + self.policy["health_seconds"]
        while True:
            if not self.docker_json("inspect", identifier)["State"]["Running"]:
                return False
            result = self.run([*self.docker, "exec", identifier, "curl", "-fsS", "--max-time", "2", "http://127.0.0.1:5000/api/health"], checked=False)
            if result.returncode == 0 and json.loads(result.stdout).get("status") == "ok":
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(1)

    def create(self, name, image, directory, network, run_id):
        result = self.run([*self.docker, "create", "--init", "--name", name, "--network", network, "--restart", "unless-stopped", "--user", f"{self.policy['data_uid']}:{self.policy['data_gid']}", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--ulimit", "core=0", "--memory", "768m", "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--mount", "type=bind,src=" + str(directory) + ",dst=/data", "-e", "ASPNETCORE_ENVIRONMENT=Production", "-e", "DOTNET_ENVIRONMENT=Production", "-e", "DATABASE_PATH=/data/game.sqlite3", "-e", "ASPNETCORE_URLS=http://0.0.0.0:5000", "-e", "SENTRY_DSN=", "--label", self.policy["owner_key"] + "=" + self.policy["owner_value"], "--label", "info.rngwars.deployment-run=" + str(run_id), "--label", "com.centurylinklabs.watchtower.enable=false", "--log-opt", "max-size=10m", "--log-opt", "max-file=3", "--health-cmd", "curl -fsS http://127.0.0.1:5000/api/health", "--health-interval", "30s", "--health-timeout", "5s", "--health-retries", "3", "--health-start-period", "40s", image], timeout=120)
        identifier = result.stdout.decode().strip()
        require(re.fullmatch(r"[a-f0-9]{64}", identifier), "updater_created_identity")
        self.container(identifier, image, directory, running=False, network=network)
        return identifier

    def apply(self, envelope):
        descriptor = os.open(self.state / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            private_path(str(self.state / "lock"), os.geteuid())
            require(not (self.state / "inflight.json").exists() and not (self.state / "inflight.json").is_symlink(), "updater_operator_recovery_required")
            request = authority.inspect(self.policy["authority_policy"], envelope)["request"]
            run_id = request["run_id"]
            area = self.state / ("attempt-" + str(run_id))
            require(not area.exists() and not area.is_symlink(), "updater_attempt_already_consumed")
            area.mkdir(mode=0o700)
            save(area / "request.json", request)
            save(self.state / "inflight.json", {"run_id": run_id})
            return self.transaction(request, envelope, area)

    def transaction(self, request, envelope, area):
        p = self.policy
        run_id = request["run_id"]
        old = self.current()
        mount = Path(p["database"]).parent
        new = None
        live_started = False
        stage = "preflight"
        def record(name, **fields):
            nonlocal stage
            stage = name
            save(area / (name + ".json"), {"at": time.time(), **fields})
        try:
            require(os.uname().machine == p["architecture"], "updater_architecture")
            host = self.run(["curl", "-q", "--fail", "--silent", "--show-error", "--noproxy", "*", "--max-time", "5", "http://169.254.169.254/hetzner/v1/metadata/instance-id"]).stdout.decode().strip()
            require(host == p["host_id"], "updater_host")
            due = self.run(["systemctl", "show", "rngwars-sqlite-backup.timer", "--property=NextElapseUSecRealtime", "--value"]).stdout.decode().strip()
            require(calendar.timegm(time.strptime(due, "%a %Y-%m-%d %H:%M:%S UTC")) - time.time() > 1200, "updater_backup_window")
            network = self.docker_json("network", "inspect", p["network"])
            require(network["Id"] == p["network_id"] and network["Name"] == p["network"] and network["Driver"] == "bridge", "updater_network")
            current = self.container(old["container_id"], old["image"], mount, running=True, network=p["network"])
            require(current["Name"] == "/" + p["workload"] and "game" in current["NetworkSettings"]["Networks"][p["network"]]["Aliases"], "updater_current_name")
            self.storage()
            record("captured", previous=old)
            evidence = area / "release"
            release = game_release.fetch(argparse.Namespace(destination=str(evidence), revision=request["image_source_revision"], digest=request["image_digest"], publication_run=str(request["publication_run_id"])))
            image = release["image"]
            self.run([*self.docker, "pull", "--platform", "linux/arm64", image], timeout=300)
            pulled = self.docker_json("image", "inspect", image)
            expected = json.loads((evidence / "config.json").read_bytes())
            require(pulled["Id"] in {request["image_digest"], release["config_digest"]} and (pulled.get("Descriptor", {}).get("digest") == request["image_digest"] or image in pulled.get("RepoDigests", [])) and pulled["Os"] == "linux" and pulled["Architecture"] == "arm64", "updater_pulled_image")
            require(all(pulled["Config"].get(key) == expected["config"].get(key) for key in ["User", "Entrypoint", "Cmd", "Env", "Labels", "WorkingDir"]) and pulled["RootFS"]["Layers"] == expected["rootfs"]["diff_ids"], "updater_pulled_configuration")
            work = self.area(Path(p["work_directory"]) / str(run_id))
            recovery = self.area(work / "recovery")
            proof = self.data("capture", p["database"], recovery, "--environment", p["backup_environment"])
            require(proof["encrypted_restore_verified"] is True and proof["retention_run"] is False and proof["snapshot"]["schema"] == p["schema"], "updater_recovery")
            record("recovered", proof=proof)
            candidate_data = self.area(work / "candidate")
            copied = self.data("copy", recovery / "restored.sqlite3", candidate_data / "game.sqlite3")
            candidate = self.create(p["workload"] + "-check-" + str(run_id), image, candidate_data, "none", run_id)
            record("candidate", container_id=candidate)
            try:
                self.run([*self.docker, "start", candidate])
                require(self.healthy(candidate), "updater_candidate_health")
                checked = self.data("inspect", candidate_data / "game.sqlite3")
                require(checked["schema"] == p["schema"] and checked["content"] == copied["content"], "updater_candidate_storage")
            finally:
                self.run([*self.docker, "stop", "--time", "20", candidate])
                self.container(candidate, image, candidate_data, running=False, network="none")
            require(authority.inspect(p["authority_policy"], envelope)["request"] == request, "updater_authority_changed")
            self.container(old["container_id"], old["image"], mount, running=True, network=p["network"])
            self.storage()
            new = self.create(p["workload"] + "-next-" + str(run_id), image, mount, p["network"], run_id)
            record("created", container_id=new)
            record("stopping_previous")
            live_started = True
            self.run([*self.docker, "stop", "--time", "20", old["container_id"]])
            self.container(old["container_id"], old["image"], mount, running=False)
            frozen = self.storage()
            record("frozen", storage=frozen)
            self.run([*self.docker, "rename", old["container_id"], p["workload"] + "-before-" + str(run_id)])
            record("starting_new")
            self.run([*self.docker, "start", new])
            require(self.healthy(new), "updater_new_health")
            require(self.storage() == frozen, "updater_new_storage")
            record("activating_new")
            self.run([*self.docker, "network", "disconnect", p["network"], new])
            self.run([*self.docker, "network", "connect", "--alias", "game", p["network"], new])
            self.run([*self.docker, "rename", new, p["workload"]])
            require(self.healthy(new), "updater_activated_health")
            value = self.container(new, image, mount, running=True)
            require(value["Name"] == "/" + p["workload"] and value["NetworkSettings"]["Networks"][p["network"]]["NetworkID"] == p["network_id"] and "game" in value["NetworkSettings"]["Networks"][p["network"]]["Aliases"], "updater_activation_identity")
            save(self.state / "current.json", {"container_id": new, "image": image}, replace=True)
            outcome = "game_deployed"
        except Exception as error:
            outcome = "operator_recovery_required" if live_started or isinstance(error, UncertainMutation) else "deployment_blocked_before_live_change"
            save(area / "failure.json", {"stage": stage, "live_change_started": live_started, "error_class": type(error).__name__, "code": str(error) if isinstance(error, Blocked) else "private_error"})
            if live_started and new is not None and not isinstance(error, UncertainMutation):
                try:
                    replacement = self.container(new, image, mount)
                    require(replacement["Name"] in {"/" + p["workload"], "/" + p["workload"] + "-next-" + str(run_id)}, "updater_rollback_target")
                    record("stopping_failed", container_id=new)
                    self.run([*self.docker, "stop", "--time", "20", new])
                    self.container(new, image, mount, running=False)
                    require(self.storage() == load(area / "frozen.json")["storage"], "updater_rollback_storage")
                    previous = self.container(old["container_id"], old["image"], mount, running=False, network=p["network"])
                    require(previous["Name"] in {"/" + p["workload"], "/" + p["workload"] + "-before-" + str(run_id)}, "updater_rollback_previous")
                    record("restoring_captured", previous=old)
                    self.run([*self.docker, "rename", new, p["workload"] + "-failed-" + str(run_id)])
                    if previous["Name"] != "/" + p["workload"]:
                        self.run([*self.docker, "rename", old["container_id"], p["workload"]])
                    self.run([*self.docker, "start", old["container_id"]])
                    require(self.healthy(old["container_id"]), "updater_rollback_health")
                    save(self.state / "current.json", old, replace=True)
                    outcome = "game_rolled_back"
                except Exception:
                    outcome = "operator_recovery_required"
        receipt = {"status": outcome, "run_id": run_id, "controller_revision": request["controller_revision"], "image_digest": request["image_digest"], "source_revision": request["image_source_revision"], "publication_run_id": request["publication_run_id"]}
        save(area / "result.json", receipt)
        save(self.state / "last-result.json", receipt, replace=True)
        if outcome != "operator_recovery_required":
            (self.state / "inflight.json").unlink()
        return receipt

    def status(self):
        last = self.state / "last-result.json"
        return {"status": "updater_status", "operator_recovery_required": (self.state / "inflight.json").exists(), "last_outcome": load(last)["status"] if last.exists() else None}


def main():
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["apply", "serve", "status"])
    parser.add_argument("--policy", required=True)
    args = parser.parse_args()
    try:
        signal.signal(signal.SIGALRM, authority.timed_out)
        signal.alarm(5)
        policy = configuration(args.policy)
        if args.operation == "serve":
            require(os.geteuid() == 0 and policy["data_uid"] == policy["data_gid"] == 10001 and policy["architecture"] == "aarch64" and policy["workload"] == policy["network"] == "rngwars-game", "updater_privileged_binding")
            with socket.socket(fileno=os.dup(0)) as peer:
                require(peer.family == socket.AF_UNIX and peer.type == socket.SOCK_STREAM, "updater_private_socket")
                pid, uid, gid = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
                require(pid > 0 and uid == policy["peer_uid"] and gid == policy["peer_gid"] and uid != 0, "updater_peer")
        raw = sys.stdin.buffer.read(8193) if args.operation != "status" else b""
        require(len(raw) <= 8192, "updater_request_size")
        envelope = json.loads(raw, object_pairs_hook=unique_object) if raw else None
        signal.alarm(900)
        updater = Updater(policy)
        result = updater.apply(envelope) if args.operation != "status" else updater.status()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] in {"game_deployed", "updater_status"} else 1
    except Blocked as error:
        print("Game updater blocked: " + str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Game updater blocked: invalid_or_unavailable_state", file=sys.stderr)
        return 1
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
