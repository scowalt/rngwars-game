#!/usr/bin/env python3
import argparse
from contextlib import closing, contextmanager
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit


class OperatorError(Exception):
    pass


class PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        raise OperatorError("invalid invocation")


def no_symlinks(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise OperatorError("symlink paths are not permitted")
    return path


def private_directory(path):
    path = no_symlinks(path)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise OperatorError("private directory required")
    return path.resolve()


def private_file(path):
    path = no_symlinks(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise OperatorError("private regular file required")
    private_directory(path.parent)
    return path.resolve()


def connection(path):
    conn = sqlite3.connect(private_file(path).as_uri() + "?mode=ro", uri=True, timeout=5)
    conn.execute("PRAGMA trusted_schema=OFF")
    return conn


def integrity(conn):
    if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise OperatorError("database integrity check failed")
    if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise OperatorError("database foreign key check failed")


def snapshot(source, destination):
    destination = Path(destination)
    parent = private_directory(destination.parent)
    if destination.exists() or destination.is_symlink():
        raise OperatorError("destination must not exist")
    with tempfile.TemporaryDirectory(prefix="sqlite-snapshot-", dir=parent) as directory:
        staged = Path(directory) / "snapshot.sqlite3"
        with closing(connection(source)) as src, closing(sqlite3.connect(staged)) as dst:
            deadline = time.monotonic() + 60

            def progress(status, remaining, total):
                if time.monotonic() > deadline:
                    raise OperatorError("snapshot timed out")

            src.backup(dst, pages=256, progress=progress, sleep=0.05)
            dst.execute("PRAGMA journal_mode=DELETE")
            integrity(dst)
        staged.chmod(0o600)
        with staged.open("rb") as handle:
            os.fsync(handle.fileno())
        os.link(staged, destination)


def record_digest(row):
    values = []
    for value in row:
        if isinstance(value, bytes):
            values.append(["blob", value.hex()])
        elif isinstance(value, float):
            values.append(["real", value.hex()])
        else:
            values.append([type(value).__name__, value])
    return hashlib.sha256(json.dumps(values, ensure_ascii=True).encode()).digest()


def database_signature(path):
    with closing(connection(path)) as conn:
        conn.execute("BEGIN")
        integrity(conn)
        schema = conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name").fetchall()
        settings = [conn.execute("PRAGMA " + name).fetchone() for name in ("user_version", "application_id", "encoding")]
        tables = []
        without_rowid = {row[1]: row[4] for row in conn.execute("PRAGMA table_list")}
        for kind, name, table, sql in schema:
            if kind == "table":
                quoted = '"' + name.replace('"', '""') + '"'
                columns = {row[1].lower() for row in conn.execute("PRAGMA table_xinfo(" + quoted + ")")}
                rowid = next((alias for alias in ("rowid", "_rowid_", "oid") if alias not in columns), None)
                selection = rowid + ",*" if rowid and not without_rowid[name] else "*"
                tables.append((name, sorted(record_digest(row) for row in conn.execute("SELECT " + selection + " FROM " + quoted))))
        return schema, settings, tables


def verify(left, right):
    if database_signature(left) != database_signature(right):
        raise OperatorError("database comparison failed")


def restic_environment(state):
    if os.environ.get("RESTIC_PASSWORD") or os.environ.get("RESTIC_PASSWORD_COMMAND"):
        raise OperatorError("password file required")
    password = private_file(os.environ["RESTIC_PASSWORD_FILE"])
    if not password.stat().st_size:
        raise OperatorError("credential file is empty")
    from backup_policy import load_policy
    policy = load_policy(os.environ["SQLITE_BACKUP_POLICY_FILE"])
    repository = os.environ["RESTIC_REPOSITORY"]
    if repository != policy["repository"]:
        raise OperatorError("backup repository does not match approved policy")
    if repository.startswith("/"):
        repo = no_symlinks(repository)
        private_directory(repo if repo.exists() else repo.parent)
    elif repository.startswith("s3:https://"):
        url = urlsplit(repository[3:])
        if not url.hostname or url.username or url.password or url.query or url.fragment or not url.path.strip("/"):
            raise OperatorError("repository configuration invalid")
        if not os.environ.get("AWS_ACCESS_KEY_ID") or not os.environ.get("AWS_SECRET_ACCESS_KEY"):
            raise OperatorError("scoped repository credentials required")
    else:
        raise OperatorError("absolute local or HTTPS S3 repository required")
    names = ("PATH", "RESTIC_REPOSITORY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_DEFAULT_REGION", "SSL_CERT_FILE", "SSL_CERT_DIR")
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(RESTIC_PASSWORD_FILE=str(password), TMPDIR=str(state), TZ="UTC",
               SQLITE_BACKUP_HOST=policy["host"], SQLITE_BACKUP_TAG=policy["tag"])
    return env


@contextmanager
def operator_state():
    state = private_directory(os.environ["SQLITE_BACKUP_STATE_DIR"])
    env = restic_environment(state)
    fd = os.open(state / ".operator.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        private_file(state / ".operator.lock")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OperatorError("another operator command is running") from None
        yield state, env


def restic(env, *args, cwd=None):
    result = subprocess.run(
        ["restic", "--no-cache", "--json", *args],
        env=env,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3600,
        check=False,
    )
    if result.returncode:
        raise OperatorError("restic operation failed; diagnostics withheld")
    return result.stdout


def repository_snapshots(env):
    return json.loads(restic(env, "snapshots", "--host", env["SQLITE_BACKUP_HOST"], "--tag", env["SQLITE_BACKUP_TAG"])) or []


def retain(env):
    restic(env, "forget", "--host", env["SQLITE_BACKUP_HOST"], "--tag", env["SQLITE_BACKUP_TAG"], "--group-by", "host,tags", "--keep-within-hourly", "7d", "--keep-within-daily", "30d", "--prune")


def backup(source, state, env):
    with tempfile.TemporaryDirectory(prefix="sqlite-backup-", dir=state) as directory:
        staged = Path(directory) / "snapshot.sqlite3"
        snapshot(source, staged)
        output = restic(env, "backup", "snapshot.sqlite3", "--host", env["SQLITE_BACKUP_HOST"], "--tag", env["SQLITE_BACKUP_TAG"], "--group-by", "host,tags", cwd=directory)
        summary = [json.loads(line) for line in output.splitlines() if line]
        snapshot_id = next(item["snapshot_id"] for item in summary if item.get("message_type") == "summary")
        if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
            raise OperatorError("backup response invalid")
    retain(env)
    return snapshot_id


def restore(snapshot_id, destination, state, env):
    if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
        raise OperatorError("full snapshot id required")
    if not any(item["id"] == snapshot_id for item in repository_snapshots(env)):
        raise OperatorError("snapshot not in designated backup set")
    destination = Path(destination)
    parent = private_directory(destination.parent)
    if destination.exists() or destination.is_symlink():
        raise OperatorError("destination must not exist")
    with tempfile.TemporaryDirectory(prefix="sqlite-restore-", dir=state) as directory:
        restic(env, "restore", snapshot_id, "--target", directory, "--verify")
        restored = Path(directory) / "snapshot.sqlite3"
        snapshot(restored, parent / destination.name)


def main():
    os.umask(0o077)
    parser = PrivateParser(description="Private SQLite operator commands; diagnostics never include data or credentials.")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=PrivateParser)
    snap = commands.add_parser("snapshot")
    snap.add_argument("source")
    snap.add_argument("destination")
    compare = commands.add_parser("verify")
    compare.add_argument("left")
    compare.add_argument("right")
    for name in ("init", "retain", "check", "snapshots"):
        commands.add_parser(name)
    save = commands.add_parser("backup")
    save.add_argument("source")
    recover = commands.add_parser("restore")
    recover.add_argument("snapshot_id")
    recover.add_argument("destination")
    args = parser.parse_args()
    suffix = ""
    if args.command == "snapshot":
        snapshot(args.source, args.destination)
    elif args.command == "verify":
        verify(args.left, args.right)
    else:
        with operator_state() as (state, env):
            if args.command == "init":
                restic(env, "init")
            elif args.command == "backup":
                suffix = " " + backup(args.source, state, env)
            elif args.command == "restore":
                restore(args.snapshot_id, args.destination, state, env)
            elif args.command == "retain":
                retain(env)
            elif args.command == "check":
                restic(env, "check", "--read-data")
            elif args.command == "snapshots":
                for item in repository_snapshots(env):
                    snapshot_id = item["id"]
                    if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
                        raise OperatorError("snapshot response invalid")
                    print(snapshot_id)
    print(args.command + " successful" + suffix)


if __name__ == "__main__":
    try:
        main()
    except OperatorError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except (Exception, KeyboardInterrupt):
        print("operator command failed; diagnostics withheld", file=sys.stderr)
        sys.exit(1)
