from pathlib import Path
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import zipfile


MAX_ARCHIVE = 64 * 1024 * 1024
MAX_FILE = 25 * 1024 * 1024
MAX_TOTAL = 50 * 1024 * 1024
MAX_FILES = 2000


class Blocked(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise Blocked(code)


def asset_path(name):
    return (
        isinstance(name, str)
        and len(name) <= 240
        and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]*", name) is not None
        and all(part and part not in {".", ".."} and not part.startswith(".") for part in name.split("/"))
    )


def archive_files(raw, extra_file=False):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE, "archive_size")
    files = {}
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            require(0 < len(entries) <= MAX_FILES + int(extra_file), "asset_count")
            for entry in entries:
                require(asset_path(entry.filename) and entry.filename == entry.orig_filename, "asset_path")
                mode = entry.external_attr >> 16
                require(stat.S_IFMT(mode) in {0, stat.S_IFREG} and not entry.is_dir(), "asset_type")
                require(not entry.flag_bits & 1 and entry.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}, "archive_encoding")
                require(entry.filename not in files, "duplicate_asset")
                require(0 <= entry.file_size <= MAX_FILE, "asset_size")
                total += entry.file_size
                require(total <= MAX_TOTAL + (1024 * 1024 if extra_file else 0), "asset_total_size")
                with archive.open(entry) as stream:
                    content = stream.read(entry.file_size + 1)
                require(len(content) == entry.file_size, "asset_size_mismatch")
                files[entry.filename] = content
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as error:
        raise Blocked("invalid_archive") from error
    return files


def assets(raw):
    files = archive_files(raw)
    require(bool(files.get("index.html")), "missing_site_index")
    return files


def encode(files):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content)
    return raw.getvalue()


def identity_fields(identity):
    require(type(identity) is dict and set(identity) == {"repository", "repository_id", "source_revision", "source_branch", "ci_run_id", "workflow_revision", "producer_run_id"}, "identity_fields")
    require(identity["repository"] == "scowalt/rngwars-game" and identity["repository_id"] == 1442331254, "repository_identity")
    require(all(type(identity[k]) is int and identity[k] > 0 for k in ["ci_run_id", "producer_run_id"]), "run_identity")
    require(all(type(identity[k]) is str and re.fullmatch(r"[a-f0-9]{40}", identity[k]) for k in ["source_revision", "workflow_revision"]), "revision_identity")
    branch = identity["source_branch"]
    require(type(branch) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,179}", branch) and not branch.startswith("refs/") and not branch.endswith(("/", ".")) and ".." not in branch and "//" not in branch and all(not part.startswith(".") and not part.endswith(".lock") for part in branch.split("/")), "branch_identity")


def bundle(raw, identity, destination):
    identity_fields(identity)
    files = assets(raw)
    manifest = {"version": 1, "identity": identity, "files": {name: {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)} for name, content in sorted(files.items())}}
    encoded = encode({"manifest.json": json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode(), **{"assets/" + name: content for name, content in files.items()}})
    inspect_bundle(encoded)
    with Path(destination).open("xb") as stream:
        stream.write(encoded)
    return hashlib.sha256(encoded).hexdigest()


def unique_object(pairs):
    require(len(dict(pairs)) == len(pairs), "duplicate_json_field")
    return dict(pairs)


def inspect_bundle(raw):
    entries = archive_files(raw, extra_file=True)
    require("manifest.json" in entries and len(entries["manifest.json"]) <= 1024 * 1024, "manifest_missing_or_large")
    try:
        manifest = json.loads(entries.pop("manifest.json"), object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as error:
        raise Blocked("invalid_manifest") from error
    require(type(manifest) is dict and set(manifest) == {"version", "identity", "files"} and type(manifest["version"]) is int and manifest["version"] == 1, "manifest_shape")
    identity_fields(manifest["identity"])
    require(all(name.startswith("assets/") for name in entries), "unexpected_bundle_file")
    files = {name.removeprefix("assets/"): content for name, content in entries.items()}
    require(bool(files.get("index.html")) and sum(map(len, files.values())) <= MAX_TOTAL, "invalid_site")
    expected = {name: {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)} for name, content in files.items()}
    require(type(manifest["files"]) is dict and all(type(meta) is dict and type(meta.get("size")) is int for meta in manifest["files"].values()) and manifest["files"] == expected, "manifest_content_mismatch")
    return manifest, files


def github(path):
    require(type(path) is str and (path == "" or path.startswith("/")) and ".." not in path and "\n" not in path, "metadata_route")
    environment = {key: os.environ[key] for key in ["PATH", "HOME", "GH_TOKEN", "GITHUB_TOKEN", "SSL_CERT_FILE", "SSL_CERT_DIR"] if key in os.environ}
    result = subprocess.run(["gh", "api", "--hostname", "github.com", "--method", "GET", "repos/scowalt/rngwars-game" + path], env=environment, capture_output=True, timeout=45)
    require(result.returncode == 0 and len(result.stdout) <= 8 * 1024 * 1024, "github_metadata_unavailable")
    try:
        return json.loads(result.stdout, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as error:
        raise Blocked("invalid_github_metadata") from error


def resolve_ci(run_id, workflow_revision, api=github):
    require(type(run_id) is int and run_id > 0 and type(workflow_revision) is str and re.fullmatch(r"[a-f0-9]{40}", workflow_revision), "ci_input")
    repository = api("")
    require(repository["id"] == 1442331254 and repository["private"] is False and repository["default_branch"] == "main", "repository_identity")
    require(api("/git/ref/heads/main")["object"]["sha"] == workflow_revision, "stale_controller_revision")
    workflow = api("/actions/workflows/ci.yml")
    require(workflow["state"] == "active" and workflow["path"] == ".github/workflows/ci.yml", "ci_workflow")
    run = api(f"/actions/runs/{run_id}")
    require(run["id"] == run_id and run["repository"]["id"] == 1442331254 and run["head_repository"]["id"] == 1442331254, "ci_repository")
    require(run["event"] in {"push", "workflow_dispatch"} and type(run["run_attempt"]) is int and run["run_attempt"] == 1, "ci_event_or_attempt")
    require(run["status"] == "completed" and run["conclusion"] == "success", "ci_result")
    require(run["workflow_id"] == workflow["id"] and run["path"] == workflow["path"], "ci_workflow")
    identity = {"repository": "scowalt/rngwars-game", "repository_id": 1442331254, "source_revision": run["head_sha"], "source_branch": run["head_branch"], "ci_run_id": run_id, "workflow_revision": workflow_revision}
    identity_fields({**identity, "producer_run_id": run_id})
    require(api("/git/ref/heads/" + run["head_branch"])["object"]["sha"] == run["head_sha"], "superseded_source_revision")
    source_ci = api("/contents/.github/workflows/ci.yml?ref=" + run["head_sha"])
    trusted_ci = api("/contents/.github/workflows/ci.yml?ref=" + workflow_revision)
    require(source_ci["type"] == trusted_ci["type"] == "file" and source_ci["sha"] == trusted_ci["sha"], "unreviewed_ci_definition")
    jobs = api(f"/actions/runs/{run_id}/attempts/1/jobs?per_page=100")
    required = {"Build API (F#)", "Build Frontend (SolidJS)", "Portable SQLite backup and deployment preparation"}
    require(jobs["total_count"] == len(jobs["jobs"]) == len(required) and {job["name"] for job in jobs["jobs"]} == required, "ci_job_set")
    require(all(job["status"] == "completed" and job["conclusion"] == "success" for job in jobs["jobs"]), "ci_job_result")
    return identity


def pack(directory, destination):
    directory = Path(directory)
    require(directory.is_dir() and not directory.is_symlink(), "invalid_asset_directory")
    files = {}
    total = 0
    root = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for relative, directories, names, parent in os.fwalk(".", dir_fd=root, follow_symlinks=False):
            prefix = "" if relative == "." else relative.removeprefix("./") + "/"
            for name in directories:
                require(asset_path(prefix + name) and stat.S_ISDIR(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode), "asset_directory_type")
            for name in names:
                require(asset_path(prefix + name), "asset_path")
                require(stat.S_ISREG(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode), "asset_type")
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                with os.fdopen(descriptor, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    require(stat.S_ISREG(info.st_mode) and 0 <= info.st_size <= MAX_FILE, "asset_size_or_type")
                    content = stream.read(MAX_FILE + 1)
                total += len(content)
                require(len(content) <= MAX_FILE and total <= MAX_TOTAL, "asset_size")
                files[prefix + name] = content
                require(len(files) <= MAX_FILES, "asset_count")
    finally:
        os.close(root)
    encoded = encode(files)
    assets(encoded)
    with Path(destination).open("xb") as stream:
        stream.write(encoded)
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "files": len(files), "asset_bytes": total}
