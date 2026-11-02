import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time


from backup_policy import load_policy


class OperatorError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise OperatorError()


def private_path(value, directory=False):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise OperatorError()
    for component in (path, *path.parents):
        if component.is_symlink():
            raise OperatorError()
    info = path.stat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600):
        raise OperatorError()
    if not directory:
        private_path(path.parent, directory=True)
    return path


def read_status(state):
    path = state / "schedule-status.json"
    if not path.exists() and not path.is_symlink():
        return None
    private_path(path)
    result = json.loads(path.read_text())
    if set(result) != {"started", "finished", "success", "last_success"} or type(result["success"]) is not bool:
        raise OperatorError()
    for key in ("started", "finished", "last_success"):
        if result[key] is not None and (type(result[key]) not in (int, float) or not 0 < result[key] <= time.time()):
            raise OperatorError()
    return result


def write_status(state, record):
    descriptor, temporary = tempfile.mkstemp(prefix="schedule-", dir=state)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, state / "schedule-status.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def environment_file(value):
    path = private_path(value)
    permitted = {"SQLITE_BACKUP_STATE_DIR", "SQLITE_BACKUP_POLICY_FILE", "RESTIC_REPOSITORY", "RESTIC_PASSWORD_FILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION", "AWS_SESSION_TOKEN", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    environment = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "TZ": "UTC"}
    for line in path.read_text().splitlines():
        if not line:
            continue
        key, separator, value = line.partition("=")
        if not separator or key not in permitted or key in environment or not value or value != value.strip() or value[0] in "\"'" or "\x00" in value:
            raise OperatorError()
        environment[key] = value
    if not {"SQLITE_BACKUP_STATE_DIR", "SQLITE_BACKUP_POLICY_FILE", "RESTIC_REPOSITORY", "RESTIC_PASSWORD_FILE"} <= environment.keys():
        raise OperatorError()
    private_path(environment["RESTIC_PASSWORD_FILE"])
    policy = load_policy(environment["SQLITE_BACKUP_POLICY_FILE"])
    if environment["RESTIC_REPOSITORY"] != policy["repository"]:
        raise OperatorError()
    if environment["RESTIC_REPOSITORY"].startswith("s3:"):
        if not {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION"} <= environment.keys() or environment["AWS_DEFAULT_REGION"] != "auto":
            raise OperatorError()
    return environment


def configure(credentials_directory, state_directory, policy_file):
    policy = load_policy(policy_file)
    credentials = private_path(credentials_directory, directory=True)
    state = private_path(state_directory, directory=True)
    values = json.loads(sys.stdin.read(1048577))
    names = ("RNGWARS_BACKUP_RESTIC_PASSWORD", "RNGWARS_BACKUP_AWS_ACCESS_KEY_ID", "RNGWARS_BACKUP_AWS_SECRET_ACCESS_KEY", "RNGWARS_BACKUP_REPOSITORY")
    if any(type(values.get(name)) is not str or not values[name] or any(character in values[name] for character in "\r\n\x00") or values[name] != values[name].strip() for name in names):
        raise OperatorError()
    if values["RNGWARS_BACKUP_REPOSITORY"] != policy["repository"]:
        raise OperatorError()
    password = credentials / "password"
    runtime = credentials / "runtime.env"
    if any(path.exists() or path.is_symlink() for path in (password, runtime)):
        raise OperatorError()
    environment = {
        "SQLITE_BACKUP_STATE_DIR": str(state), "SQLITE_BACKUP_POLICY_FILE": str(policy_file), "RESTIC_PASSWORD_FILE": str(password),
        "RESTIC_REPOSITORY": values["RNGWARS_BACKUP_REPOSITORY"], "AWS_DEFAULT_REGION": "auto",
        "AWS_ACCESS_KEY_ID": values["RNGWARS_BACKUP_AWS_ACCESS_KEY_ID"], "AWS_SECRET_ACCESS_KEY": values["RNGWARS_BACKUP_AWS_SECRET_ACCESS_KEY"],
    }
    created = []
    try:
        for path, content in ((password, values["RNGWARS_BACKUP_RESTIC_PASSWORD"] + "\n"), (runtime, "".join(f"{key}={value}\n" for key, value in environment.items()))):
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            created.append(path)
            with os.fdopen(descriptor, "w") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
    except Exception:
        for path in created:
            path.unlink()
        raise
    print("backup recovery configuration installed; repository initialization remains explicit")
    return 0


def main():
    os.umask(0o077)
    parser = Parser()
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("database")
    run.add_argument("--environment", required=True)
    status = commands.add_parser("status")
    status.add_argument("--state", required=True)
    validation = commands.add_parser("validate")
    validation.add_argument("--data-directory", required=True)
    validation.add_argument("--image", required=True)
    validation.add_argument("--policy", required=True)
    operator = commands.add_parser("operator")
    operator.add_argument("--environment", required=True)
    operator.add_argument("arguments", nargs=argparse.REMAINDER)
    configuration = commands.add_parser("configure")
    configuration.add_argument("--credentials-directory", required=True)
    configuration.add_argument("--state", required=True)
    configuration.add_argument("--policy", required=True)
    args = parser.parse_args()
    if args.command == "validate":
        policy = load_policy(args.policy)
        if not re.fullmatch(re.escape(policy["image_repository"]) + r"@sha256:[a-f0-9]{64}", args.image) or args.data_directory != policy["data_directory"]:
            raise OperatorError()
        directory = private_path(args.data_directory, directory=True)
        database = private_path(directory / "game.sqlite3")
        if database.stat().st_size == 0:
            raise OperatorError()
        for suffix in ("-wal", "-shm"):
            path = directory / ("game.sqlite3" + suffix)
            if path.exists() or path.is_symlink():
                private_path(path)
        print("deployment storage and image preflight passed; native schema and final-primary verification remain required")
        return 0
    if args.command == "operator":
        environment = environment_file(args.environment)
        private_path(environment["SQLITE_BACKUP_STATE_DIR"], directory=True)
        return subprocess.run([sys.executable, str(Path(__file__).with_name("sqlite-backup.py")), *args.arguments], env=environment).returncode
    if args.command == "configure":
        return configure(args.credentials_directory, args.state, args.policy)
    if args.command == "status":
        record = read_status(private_path(args.state, directory=True))
        if record is None or record["last_success"] is None:
            print("backup schedule missing successful run")
            return 1
        if not record["success"]:
            print("backup schedule last run failed")
            return 1
        if time.time() - record["last_success"] > 5400:
            print("backup schedule missed hourly run")
            return 1
        print("backup schedule healthy")
        return 0
    environment = environment_file(args.environment)
    state = private_path(environment["SQLITE_BACKUP_STATE_DIR"], directory=True)
    lock_path = state / "schedule.lock"
    if lock_path.exists() or lock_path.is_symlink():
        private_path(lock_path)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return scheduled_backup(args.database, environment, state)


def scheduled_backup(database, environment, state):
    previous = read_status(state)
    started = time.time()
    write_status(state, {"started": started, "finished": started, "success": False, "last_success": previous["last_success"] if previous else None})
    result = subprocess.run([sys.executable, str(Path(__file__).with_name("sqlite-backup.py")), "backup", database], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    success = result.returncode == 0
    write_status(state, {"started": started, "finished": time.time(), "success": success, "last_success": started if success else previous["last_success"] if previous else None})
    print("backup schedule successful" if success else "backup schedule failed; inspect protected operator checks")
    return 0 if success else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print("backup schedule configuration or state rejected", file=sys.stderr)
        sys.exit(1)
