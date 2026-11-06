import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import stat
import subprocess
import sys
import tempfile
import urllib.parse

from marketing_artifact import Blocked, require, unique_object


REPOSITORY = "scowalt/rngwars-game"
IMAGE = "ghcr.io/scowalt/rngwars-game-releases"
WORKFLOW = REPOSITORY + "/.github/workflows/game-publication.yml@refs/heads/main"
MAX_JSON = 2 * 1024 * 1024


def bounded_file(value, limit=MAX_JSON):
    path = Path(value)
    require(path.is_absolute() and not path.is_symlink(), "release_file_path")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= limit, "release_file_bounds")
        content = stream.read(limit + 1)
    require(len(content) == info.st_size, "release_file_changed")
    return content


def execute(command, environment, limit=MAX_JSON):
    result = subprocess.run(command, env=environment, capture_output=True, timeout=90)
    require(result.returncode == 0 and 0 < len(result.stdout) <= limit, "release_verification_tool_failed")
    return json.loads(result.stdout, object_pairs_hook=unique_object)


def github(path, environment):
    return execute(["curl", "-q", "--proto", "=https", "--connect-timeout", "10", "--max-time", "30", "--max-filesize", str(MAX_JSON), "--fail", "--silent", "--show-error", "--request", "GET", "--header", "Accept: application/vnd.github+json", "https://api.github.com/repos/" + REPOSITORY + path], environment)


def verify(args):
    require(re.fullmatch(r"[a-f0-9]{40}", args.revision) and re.fullmatch(r"sha256:[a-f0-9]{64}", args.digest), "release_identity")
    require(re.fullmatch(r"[1-9][0-9]{0,19}", args.publication_run), "release_run_id")
    run_id = int(args.publication_run)
    manifest_bytes = bounded_file(args.manifest)
    require("sha256:" + hashlib.sha256(manifest_bytes).hexdigest() == args.digest, "release_manifest_digest")
    manifest = json.loads(manifest_bytes, object_pairs_hook=unique_object)
    media = "application/vnd.oci.image."
    require(type(manifest["schemaVersion"]) is int and manifest["schemaVersion"] == 2 and manifest["mediaType"] == media + "manifest.v1+json", "release_manifest_shape")
    require(type(manifest["layers"]) is list and 1 <= len(manifest["layers"]) <= 64, "release_manifest_shape")
    for descriptor in [manifest["config"], *manifest["layers"]]:
        require(type(descriptor) is dict and set(descriptor) <= {"mediaType", "digest", "size", "annotations"} and re.fullmatch(r"sha256:[a-f0-9]{64}", descriptor["digest"]) and type(descriptor["size"]) is int and 0 < descriptor["size"] <= 1024 ** 3, "release_manifest_shape")
    require(manifest["config"]["mediaType"] == media + "config.v1+json" and all(layer["mediaType"] in {media + "layer.v1.tar", media + "layer.v1.tar+gzip"} for layer in manifest["layers"]), "release_manifest_shape")
    config_bytes = bounded_file(args.config)
    config_digest = "sha256:" + hashlib.sha256(config_bytes).hexdigest()
    require(manifest["config"]["digest"] == config_digest and manifest["config"]["size"] == len(config_bytes), "release_config_digest")
    config = json.loads(config_bytes, object_pairs_hook=unique_object)
    rootfs = config["rootfs"]
    require(rootfs["type"] == "layers" and type(rootfs["diff_ids"]) is list and len(rootfs["diff_ids"]) == len(manifest["layers"]) and all(type(value) is str and re.fullmatch(r"sha256:[a-f0-9]{64}", value) for value in rootfs["diff_ids"]), "release_rootfs_binding")
    runtime = config["config"]
    require(config["os"] == "linux" and config["architecture"] == "arm64" and runtime["User"] == "10001:10001" and runtime["Entrypoint"] == ["/app/game-entrypoint.sh"] and runtime["Cmd"] == ["dotnet", "RNGWars.Api.dll"] and runtime["Labels"]["org.opencontainers.image.revision"] == args.revision and runtime["Labels"]["org.opencontainers.image.source"] == "https://github.com/" + REPOSITORY, "release_runtime_identity")
    bundle_bytes = bounded_file(args.bundle)
    root_bytes = bounded_file(args.trusted_root)
    with tempfile.TemporaryDirectory(prefix="game-release-verifier-") as directory:
        home = Path(directory)
        for name, content in [("manifest.json", manifest_bytes), ("bundle.jsonl", bundle_bytes), ("trusted-root.jsonl", root_bytes)]:
            path = home / name
            with path.open("xb") as stream:
                stream.write(content)
            path.chmod(0o400)
        environment = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(home), "GH_CONFIG_DIR": str(home), "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
        run = github(f"/actions/runs/{run_id}", environment)
        require(run["status"] == "completed" and run["conclusion"] == "success", "release_publication_not_successful")
        require(run["id"] == run_id and run["repository"]["id"] == run["head_repository"]["id"] == 1442331254 and run["head_sha"] == args.revision and run["head_branch"] == "main" and run["path"] == ".github/workflows/game-publication.yml" and run["actor"]["id"] == run["triggering_actor"]["id"] == 1100550 and run["event"] in {"workflow_dispatch", "workflow_run"} and type(run["run_attempt"]) is int and run["run_attempt"] == 1, "release_publication_identity")
        jobs = github(f"/actions/runs/{run_id}/attempts/1/jobs?per_page=100", environment)
        require(jobs["total_count"] == len(jobs["jobs"]) == 4 and {job["name"] for job in jobs["jobs"]} == {"resolve", "Build and exercise native image", "prepare", "publish"}, "release_publication_jobs")
        require(all(job["run_id"] == run_id and job["status"] == "completed" and job["conclusion"] == "success" and job["labels"] == ["ubuntu-24.04-arm" if job["name"] == "Build and exercise native image" else "ubuntu-24.04"] for job in jobs["jobs"]), "release_publication_jobs")
        command = ["gh", "attestation", "verify", str(home / "manifest.json"), "--bundle", str(home / "bundle.jsonl"), "--custom-trusted-root", str(home / "trusted-root.jsonl"), "--repo", REPOSITORY, "--cert-identity", "https://github.com/" + WORKFLOW, "--cert-oidc-issuer", "https://token.actions.githubusercontent.com", "--signer-digest", args.revision, "--source-digest", args.revision, "--source-ref", "refs/heads/main", "--deny-self-hosted-runners", "--predicate-type", "https://slsa.dev/provenance/v1", "--format", "json"]
        records = execute(command, environment, 8 * MAX_JSON)
        require(type(records) is list and 0 < len(records) <= 30, "release_attestation_results")
        invocation = f"https://github.com/{REPOSITORY}/actions/runs/{run_id}/attempts/1"
        matching = [record["verificationResult"]["statement"] for record in records if record["verificationResult"]["statement"]["predicate"].get("runDetails", {}).get("metadata", {}).get("invocationId") == invocation]
        require(any(statement["predicateType"] == "https://slsa.dev/provenance/v1" and any(subject.get("name") == IMAGE and subject.get("digest", {}).get("sha256") == args.digest.removeprefix("sha256:") for subject in statement["subject"]) for statement in matching), "release_attestation_binding")
    return {"status": "release_verified_not_deployment_approval", "image": IMAGE + "@" + args.digest, "source_revision": args.revision, "publication_run_id": run_id, "config_digest": config_digest}


def registry(url, environment, authorization=None, blob_redirect=False):
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == "https" and parsed.hostname in {"ghcr.io", "pkg-containers.githubusercontent.com"} and parsed.port in {None, 443} and not parsed.username and not parsed.password and not parsed.fragment and len(url) <= 8192, "release_registry_origin")
    with tempfile.TemporaryDirectory(prefix="registry-headers-", dir=environment["HOME"]) as directory:
        headers = Path(directory) / "headers"
        headers.touch(mode=0o600)
        configuration = ["silent", "show-error", 'proto = "=https"', "max-time = 30", "max-filesize = " + str(MAX_JSON), "url = " + json.dumps(url), 'request = "GET"', "dump-header = " + json.dumps(str(headers)), 'write-out = "\\n%{http_code}"', 'header = "Accept: application/vnd.oci.image.manifest.v1+json"']
        if authorization:
            require(parsed.hostname == "ghcr.io", "release_registry_authorization_origin")
            configuration.append("header = " + json.dumps("Authorization: " + authorization))
        result = subprocess.run(["curl", "-q", "--config", "-"], input=("\n".join(configuration) + "\n").encode(), env=environment, capture_output=True, timeout=40)
        require(result.returncode == 0 and len(result.stdout) <= MAX_JSON + 4, "release_registry_transport")
        body, separator, code = result.stdout.rpartition(b"\n")
        require(separator and re.fullmatch(rb"[1-5][0-9]{2}", code), "release_registry_status")
        if code in {b"302", b"307"} and blob_redirect:
            require(headers.stat().st_size <= 32768, "release_registry_headers")
            locations = [line.partition(b":")[2].strip().decode("ascii") for line in headers.read_bytes().splitlines() if line.lower().startswith(b"location:")]
            require(len(locations) == 1 and urllib.parse.urlsplit(locations[0]).hostname == "pkg-containers.githubusercontent.com", "release_registry_redirect")
            return registry(locations[0], environment)
        require(code == b"200" and body, "release_registry_http_" + code.decode())
        return body


def fetch(args):
    require(re.fullmatch(r"[a-f0-9]{40}", args.revision) and re.fullmatch(r"sha256:[a-f0-9]{64}", args.digest) and re.fullmatch(r"[1-9][0-9]{0,19}", args.publication_run), "release_identity")
    destination = Path(args.destination)
    require(destination.is_absolute() and not destination.exists() and not destination.is_symlink(), "release_destination_exists")
    require(not any(part.is_symlink() for part in destination.parents), "release_destination_path")
    with tempfile.TemporaryDirectory(prefix="game-release-fetch-", dir=destination.parent) as directory:
        root = Path(directory)
        environment = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(root), "GH_CONFIG_DIR": str(root), "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
        query = urllib.parse.urlencode({"service": "ghcr.io", "scope": "repository:scowalt/rngwars-game-releases:pull"})
        token = json.loads(registry("https://ghcr.io/token?" + query, environment), object_pairs_hook=unique_object)["token"]
        require(type(token) is str and 0 < len(token) <= 65536 and not any(value in token for value in "\r\n\x00"), "release_registry_token")
        manifest = registry("https://ghcr.io/v2/scowalt/rngwars-game-releases/manifests/" + args.digest, environment, "Bearer " + token)
        require("sha256:" + hashlib.sha256(manifest).hexdigest() == args.digest, "release_manifest_digest")
        config_digest = json.loads(manifest, object_pairs_hook=unique_object)["config"]["digest"]
        require(type(config_digest) is str and re.fullmatch(r"sha256:[a-f0-9]{64}", config_digest), "release_config_digest")
        config = registry("https://ghcr.io/v2/scowalt/rngwars-game-releases/blobs/" + config_digest, environment, "Bearer " + token, blob_redirect=True)
        response = github("/attestations/" + args.digest, environment)
        bundles = response["attestations"]
        require(type(bundles) is list and 0 < len(bundles) <= 30, "release_bundle_inventory")
        bundle = b"".join(json.dumps(item["bundle"]).encode() + b"\n" for item in bundles)
        result = subprocess.run(["gh", "attestation", "trusted-root"], env=environment, capture_output=True, timeout=90)
        require(result.returncode == 0 and 0 < len(result.stdout) <= MAX_JSON and len(bundle) <= MAX_JSON, "release_trusted_root_unavailable")
        files = {"manifest.json": manifest, "config.json": config, "bundle.jsonl": bundle, "trusted-root.jsonl": result.stdout}
        for name, content in files.items():
            with (root / name).open("xb") as stream:
                stream.write(content)
            (root / name).chmod(0o400)
        checked = verify(argparse.Namespace(revision=args.revision, digest=args.digest, publication_run=args.publication_run, manifest=str(root / "manifest.json"), config=str(root / "config.json"), bundle=str(root / "bundle.jsonl"), trusted_root=str(root / "trusted-root.jsonl")))
        destination.mkdir(mode=0o700)
        for name in files:
            os.link(root / name, destination / name)
    return checked


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="operation", required=True)
    command = commands.add_parser("verify")
    command.add_argument("manifest")
    command.add_argument("config")
    command.add_argument("bundle")
    command.add_argument("--trusted-root", required=True)
    download = commands.add_parser("fetch")
    download.add_argument("destination")
    for selected in [command, download]:
        selected.add_argument("--revision", required=True)
        selected.add_argument("--digest", required=True)
        selected.add_argument("--publication-run", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(fetch(args) if args.operation == "fetch" else verify(args), sort_keys=True))
        return 0
    except Blocked as error:
        print("Game release blocked: " + str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Game release blocked: invalid_or_unavailable_evidence", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
