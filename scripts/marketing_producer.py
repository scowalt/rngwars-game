import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
import zlib
import marketing_artifact as m


REPOSITORY = "scowalt/rngwars-game"
WORKFLOW = REPOSITORY + "/.github/workflows/marketing-artifact.yml@refs/heads/main"


def identifier(value):
    m.require(type(value) is str and re.fullmatch(r"[1-9][0-9]{0,19}", value), "invalid_identifier")
    return int(value)


def context(env):
    m.require(env.get("GITHUB_REPOSITORY") == REPOSITORY and env.get("GITHUB_REPOSITORY_ID") == "1442331254", "producer_repository")
    m.require(env.get("GITHUB_REF") == "refs/heads/main" and env.get("GITHUB_WORKFLOW_REF") == WORKFLOW, "producer_workflow")
    m.require(env.get("GITHUB_RUN_ATTEMPT") == "1", "producer_rerun")
    revision = env.get("GITHUB_WORKFLOW_SHA", "")
    m.require(re.fullmatch(r"[a-f0-9]{40}", revision), "producer_revision")
    return identifier(env.get("SOURCE_CI_RUN_ID", "")), revision, identifier(env.get("GITHUB_RUN_ID", ""))


def single_file(raw, name):
    m.require(type(raw) is bytes and 0 < len(raw) <= m.MAX_ARCHIVE, "artifact_archive_size")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            m.require(len(entries) == 1, "artifact_archive_entries")
            entry = entries[0]
            m.require(entry.filename == entry.orig_filename == name and not entry.is_dir(), "artifact_archive_path")
            m.require(stat.S_IFMT(entry.external_attr >> 16) in {0, stat.S_IFREG}, "artifact_archive_type")
            m.require(not entry.flag_bits & 1 and entry.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}, "artifact_archive_encoding")
            m.require(0 < entry.file_size <= m.MAX_ARCHIVE, "artifact_file_size")
            with archive.open(entry) as stream:
                content = stream.read(entry.file_size + 1)
            m.require(len(content) == entry.file_size, "artifact_file_size_mismatch")
            return content
    except (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError, EOFError) as error:
        raise m.Blocked("invalid_artifact_archive") from error


def receive(metadata, raw, artifact_id, run_id, revision):
    m.require(metadata["id"] == artifact_id and metadata["name"] == f"marketing-unsealed-{run_id}-1" and metadata["expired"] is False, "artifact_identity")
    m.require(type(metadata["size_in_bytes"]) is int and 0 < metadata["size_in_bytes"] <= m.MAX_ARCHIVE, "artifact_size")
    run = metadata["workflow_run"]
    m.require(run["id"] == run_id and run["repository_id"] == 1442331254 and run["head_repository_id"] == 1442331254 and run["head_sha"] == revision and run["head_branch"] == "main", "artifact_producer")
    m.require(type(raw) is bytes and len(raw) <= m.MAX_ARCHIVE and metadata["digest"] == "sha256:" + hashlib.sha256(raw).hexdigest(), "artifact_transport_digest")
    return single_file(raw, "assets.zip")


def client_environment():
    return {key: os.environ[key] for key in ["PATH", "HOME", "GH_TOKEN", "GITHUB_TOKEN", "SSL_CERT_FILE", "SSL_CERT_DIR"] if key in os.environ}


def verify_signature(raw, revision, run_id, runner=subprocess.run):
    m.require(type(raw) is bytes and 0 < len(raw) <= m.MAX_ARCHIVE and type(revision) is str and re.fullmatch(r"[a-f0-9]{40}", revision) and type(run_id) is int and run_id > 0, "attestation_input")
    digest = hashlib.sha256(raw).hexdigest()
    with tempfile.TemporaryDirectory(prefix="marketing-verify-") as temporary:
        path = Path(temporary) / "release.zip"
        with path.open("xb") as stream:
            stream.write(raw)
        path.chmod(0o400)
        command = ["gh", "attestation", "verify", str(path), "--hostname", "github.com", "--repo", REPOSITORY, "--cert-identity", "https://github.com/" + WORKFLOW, "--cert-oidc-issuer", "https://token.actions.githubusercontent.com", "--signer-digest", revision, "--source-digest", revision, "--source-ref", "refs/heads/main", "--deny-self-hosted-runners", "--predicate-type", "https://slsa.dev/provenance/v1", "--format", "json", "--limit", "30"]
        result = runner(command, env=client_environment(), capture_output=True, timeout=90)
    m.require(result.returncode == 0 and len(result.stdout) <= 8 * 1024 * 1024, "attestation_verification_failed")
    verified = json.loads(result.stdout, object_pairs_hook=m.unique_object)
    m.require(type(verified) is list and 0 < len(verified) <= 30, "attestation_results")
    expected_run = f"https://github.com/{REPOSITORY}/actions/runs/{run_id}/attempts/1"
    for entry in verified:
        statement = entry["verificationResult"]["statement"]
        if statement["predicateType"] == "https://slsa.dev/provenance/v1" and any(subject.get("digest", {}).get("sha256") == digest for subject in statement["subject"]) and statement["predicate"].get("runDetails", {}).get("metadata", {}).get("invocationId") == expected_run:
            return digest
    raise m.Blocked("attestation_invocation_mismatch")


def download(artifact_id):
    m.require(type(artifact_id) is int and artifact_id > 0, "artifact_id")
    command = ["gh", "api", "--hostname", "github.com", "--method", "GET", f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip", "--allow-escape-sequences"]
    result = subprocess.run(command, env=client_environment(), capture_output=True, timeout=90)
    m.require(result.returncode == 0 and 0 < len(result.stdout) <= m.MAX_ARCHIVE, "artifact_download_failed")
    return result.stdout


def output(values):
    path = os.environ.get("GITHUB_OUTPUT")
    m.require(path is not None and all(re.fullmatch(r"[a-z][a-z0-9_]*", key) and re.fullmatch(r"[a-zA-Z0-9/._-]+", str(value)) for key, value in values.items()), "invalid_step_output")
    with open(path, "a", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("resolve")
    packing = commands.add_parser("pack")
    packing.add_argument("directory")
    packing.add_argument("destination")
    sealing = commands.add_parser("seal")
    sealing.add_argument("destination")
    checking = commands.add_parser("verify")
    checking.add_argument("bundle")
    args = parser.parse_args()
    if args.command == "pack":
        result = m.pack(args.directory, args.destination)
        print(json.dumps({"status": "untrusted_assets_packaged", **result}))
        return
    ci_run, revision, run_id = context(os.environ)
    identity = {**m.resolve_ci(ci_run, revision), "producer_run_id": run_id}
    if args.command == "resolve":
        output({"source_revision": identity["source_revision"], "source_branch": identity["source_branch"]})
        print(json.dumps({"status": "exact_CI_source_resolved", **identity}))
    elif args.command == "seal":
        artifact_id = identifier(os.environ.get("SOURCE_ARTIFACT_ID", ""))
        metadata = m.github(f"/actions/artifacts/{artifact_id}")
        m.require(type(metadata.get("size_in_bytes")) is int and 0 < metadata["size_in_bytes"] <= m.MAX_ARCHIVE, "artifact_size")
        raw = receive(metadata, download(artifact_id), artifact_id, run_id, revision)
        destination = Path(args.destination)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        digest = m.bundle(raw, identity, destination)
        output({"bundle_sha256": digest})
        print(json.dumps({"status": "bundle_prepared_not_yet_attested", "sha256": digest, **identity}))
    else:
        path = Path(args.bundle)
        m.require(path.is_file() and not path.is_symlink() and path.stat().st_size <= m.MAX_ARCHIVE, "bundle_file")
        raw = path.read_bytes()
        manifest, _ = m.inspect_bundle(raw)
        m.require(manifest["identity"] == identity, "bundle_identity_mismatch")
        digest = verify_signature(raw, revision, run_id)
        print(json.dumps({"status": "authentic_artifact_signature_verified_no_deployment", "sha256": digest, **identity}))


if __name__ == "__main__":
    try:
        main()
    except m.Blocked as error:
        print("Marketing artifact blocked: " + str(error), file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        print("Marketing artifact blocked: local_or_provider_failure", file=sys.stderr)
        raise SystemExit(1)
