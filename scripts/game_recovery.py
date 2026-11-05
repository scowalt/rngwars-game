import argparse
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import sys

from marketing_artifact import require


def helper(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = helper("deployment_sqlite_backup", "sqlite-backup.py")
schedule = helper("deployment_backup_schedule", "sqlite-backup-schedule.py")


def describe(path):
    path = backup.private_file(path)
    info = path.stat()
    require(info.st_nlink == 1 and info.st_size > 0 and info.st_mode & 0o777 == 0o600, "storage_file")
    for suffix in ["-wal", "-shm"]:
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            require(backup.private_file(sidecar).stat().st_nlink == 1, "storage_sidecar")
    signature = backup.database_signature(path)
    require(signature[1][1] == (0x524E4757,), "storage_initialization_marker")
    journals = [table for table in signature[2] if table[0].lower() == "schemaversions"]
    require(len(journals) == 1 and len(journals[0][1]) > 0, "storage_migrations")
    digest = lambda value: hashlib.sha256(json.dumps(value, default=lambda item: item.hex(), sort_keys=True).encode()).hexdigest()
    return {"schema": digest([signature[0], signature[1], journals]), "content": digest(signature), "device": info.st_dev, "inode": info.st_ino}


def capture(database, area, environment_file):
    area = backup.private_directory(area)
    require(not any(area.iterdir()), "recovery_destination_used")
    original = describe(database)
    environment = schedule.environment_file(environment_file)
    os.environ.clear()
    os.environ.update(environment)
    with backup.operator_state() as (state, env):
        before = {row["id"] for row in backup.repository_snapshots(env)}
        snapshot = area / "snapshot.sqlite3"
        backup.snapshot(database, snapshot)
        output = backup.restic(env, "backup", "snapshot.sqlite3", "--host", env["SQLITE_BACKUP_HOST"], "--tag", env["SQLITE_BACKUP_TAG"], "--group-by", "host,tags", cwd=area)
        summaries = [json.loads(line) for line in output.splitlines() if line]
        identifiers = [row["snapshot_id"] for row in summaries if row.get("message_type") == "summary"]
        require(len(identifiers) == 1 and re.fullmatch(r"[a-f0-9]{64}", identifiers[0]), "recovery_snapshot_identity")
        backup.restore(identifiers[0], area / "restored.sqlite3", state, env)
        backup.verify(snapshot, area / "restored.sqlite3")
        require(before <= {row["id"] for row in backup.repository_snapshots(env)}, "recovery_points_changed")
    require(describe(database)["schema"] == original["schema"], "recovery_schema_changed")
    return {"encrypted_restore_verified": True, "retention_run": False, "snapshot_id": identifiers[0], "snapshot": describe(snapshot)}


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("database")
    copy = commands.add_parser("copy")
    copy.add_argument("database")
    copy.add_argument("destination")
    recovery = commands.add_parser("capture")
    recovery.add_argument("database")
    recovery.add_argument("destination")
    recovery.add_argument("--environment", required=True)
    args = parser.parse_args()
    try:
        if args.command == "capture":
            result = capture(args.database, args.destination, args.environment)
        elif args.command == "copy":
            describe(args.database)
            backup.snapshot(args.database, args.destination)
            result = describe(args.destination)
        else:
            result = describe(args.database)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print("Deployment recovery blocked; private diagnostics withheld", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
