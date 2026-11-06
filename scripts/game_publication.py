import argparse
import base64
import datetime
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
import zipfile

import game_artifact
import game_automation

import marketing_artifact as metadata
from marketing_artifact import Blocked, require
from marketing_producer import client_environment, identifier, output


REPOSITORY = "scowalt/rngwars-game"
WORKFLOW = REPOSITORY + "/.github/workflows/game-publication.yml@refs/heads/main"
IMAGE = "ghcr.io/scowalt/rngwars-game-releases"
OPERATION_STAGE = "resolve"


def context(env):
    require(env.get("GITHUB_ACTIONS") == "true" and env.get("GITHUB_REPOSITORY") == REPOSITORY and env.get("GITHUB_REPOSITORY_ID") == "1442331254" and env.get("GITHUB_REPOSITORY_OWNER_ID") == "1100550", "game_publication_repository")
    require(env.get("GITHUB_REF") == "refs/heads/main" and env.get("GITHUB_WORKFLOW_REF") == WORKFLOW and env.get("GITHUB_EVENT_NAME") in {"workflow_dispatch", "workflow_run"} and env.get("GITHUB_RUN_ATTEMPT") == "1", "game_publication_context")
    require(env.get("GITHUB_ACTOR") == env.get("GITHUB_TRIGGERING_ACTOR") == "scowalt" and env.get("GITHUB_ACTOR_ID") == "1100550", "game_publication_actor")
    revision = env.get("GITHUB_SHA", "")
    require(re.fullmatch(r"[a-f0-9]{40}", revision) and env.get("GITHUB_WORKFLOW_SHA") == env.get("APPROVED_REVISION") == revision, "game_publication_revision")
    return revision, identifier(env.get("GITHUB_RUN_ID", "")), identifier(env.get("SOURCE_CI_RUN_ID", ""))


def resolve(env):
    revision, run_id, ci_run = context(env)
    if env.get("GAME_PUBLICATION_OPERATION") == "publish":
        publication_configuration(env)
    identity = metadata.resolve_ci(ci_run, revision)
    if env.get("GITHUB_EVENT_NAME") == "workflow_run":
        require(env.get("GAME_AUTOMATIC_CD_ENABLED") == "true", "automatic_game_disabled")
        game_automation.push_ci(ci_run, revision, api=metadata.github)
    source_run = metadata.github(f"/actions/runs/{ci_run}")
    created = datetime.datetime.fromisoformat(source_run["created_at"])
    require(created.tzinfo is not None and -300 <= (datetime.datetime.now(datetime.timezone.utc) - created).total_seconds() <= 86400, "game_CI_freshness")
    require(identity["source_branch"] == "main" and identity["source_revision"] == revision, "game_main_source_required")
    workflow = metadata.github("/actions/workflows/game-publication.yml")
    run = metadata.github(f"/actions/runs/{run_id}")
    require(workflow["state"] == "active" and workflow["path"] == run["path"] == ".github/workflows/game-publication.yml" and run["workflow_id"] == workflow["id"] and run["id"] == run_id, "game_publication_workflow")
    require(run["repository"]["id"] == run["head_repository"]["id"] == 1442331254 and run["head_sha"] == revision and run["head_branch"] == "main" and run["actor"]["id"] == run["triggering_actor"]["id"] == 1100550, "game_publication_run_identity")
    require(run["event"] == env["GITHUB_EVENT_NAME"] and type(run["run_attempt"]) is int and run["run_attempt"] == 1 and run["status"] == "in_progress", "game_publication_run_state")
    return {"status": "game_source_resolved_no_publication", **identity, "publication_run_id": run_id}


def prepare(identity, artifact_id, destination):
    destination = Path(destination)
    require(destination.is_absolute() and not destination.exists() and not destination.is_symlink(), "candidate_destination_exists")
    run_id = identity["publication_run_id"]
    revision = identity["source_revision"]
    artifact = metadata.github(f"/actions/artifacts/{artifact_id}")
    relation = artifact["workflow_run"]
    require(artifact["id"] == artifact_id and artifact["name"] == f"game-image-{run_id}-1" and artifact["expired"] is False, "game_artifact_identity")
    require(relation["id"] == run_id and relation["repository_id"] == relation["head_repository_id"] == 1442331254 and relation["head_sha"] == revision and relation["head_branch"] == "main", "game_artifact_run")
    maximum = game_artifact.MAX_ARCHIVE + 8 * 1024 * 1024
    require(type(artifact["size_in_bytes"]) is int and 0 < artifact["size_in_bytes"] <= maximum, "game_artifact_size")
    jobs = metadata.github(f"/actions/runs/{run_id}/attempts/1/jobs?per_page=100")
    require(jobs["total_count"] == len(jobs["jobs"]) < 100, "game_build_inventory")
    native = [job for job in jobs["jobs"] if job["name"] == "Build and exercise native image"]
    require(len(native) == 1 and native[0]["run_id"] == run_id and native[0]["status"] == "completed" and native[0]["conclusion"] == "success" and native[0]["labels"] == ["ubuntu-24.04-arm"], "game_native_job_result")
    with tempfile.TemporaryDirectory(prefix="game-candidate-", dir=destination.parent) as directory:
        root = Path(directory)
        raw = root / "transport.zip"
        with raw.open("xb") as stream:
            result = subprocess.run(["gh", "api", "--hostname", "github.com", "--method", "GET", "--allow-escape-sequences", f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip"], env=client_environment(), stdout=stream, stderr=subprocess.PIPE, timeout=180)
        require(result.returncode == 0 and 0 < raw.stat().st_size <= maximum, "game_artifact_download")
        with raw.open("rb") as stream:
            require("sha256:" + hashlib.file_digest(stream, "sha256").hexdigest() == artifact["digest"], "game_transport_digest")
        with zipfile.ZipFile(raw) as transport:
            entries = transport.infolist()
            require(len(entries) == 2 and {entry.filename for entry in entries} == {"image.oci.tar", "native-game-result.json"}, "game_artifact_members")
            for entry in entries:
                limit = game_artifact.MAX_ARCHIVE if entry.filename == "image.oci.tar" else 65536
                require(entry.filename == entry.orig_filename and not entry.is_dir() and stat.S_IFMT(entry.external_attr >> 16) in {0, stat.S_IFREG}, "game_artifact_file_type")
                require(not entry.flag_bits & 1 and entry.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED} and 0 < entry.file_size <= limit, "game_artifact_file_size")
                total = 0
                with transport.open(entry) as source, (root / entry.filename).open("xb") as target:
                    while chunk := source.read(1024 * 1024):
                        total += len(chunk)
                        require(total <= limit, "game_artifact_file_size")
                        target.write(chunk)
                require(total == entry.file_size, "game_artifact_file_size")
        info = game_artifact.verify_native(root / "native-game-result.json", game_artifact.inspect(root / "image.oci.tar", revision))
        require(metadata.github("/git/ref/heads/main")["object"]["sha"] == revision, "stale_game_candidate")
        destination.mkdir(mode=0o700)
        for name in ["image.oci.tar", "native-game-result.json"]:
            os.link(root / name, destination / name)
            (destination / name).chmod(0o400)
    return {**identity, **info, "status": "native_candidate_verified_no_publication", "artifact_id": artifact_id, "native_job_id": native[0]["id"]}


def publication_configuration(env):
    require(env.get("GAME_PUBLICATION_ENABLED") == "true", "game_publication_disabled")
    environment = metadata.github("/environments/game-publication")
    require(environment["name"] == "game-publication" and environment["can_admins_bypass"] is False and environment["deployment_branch_policy"] == {"protected_branches": False, "custom_branch_policies": True}, "game_publication_environment")
    reviewers = [rule for rule in environment["protection_rules"] if rule["type"] == "required_reviewers"]
    if env.get("GITHUB_EVENT_NAME") == "workflow_run":
        require(env.get("GAME_AUTOMATIC_CD_ENABLED") == "true" and not reviewers, "automatic_publication_environment")
    else:
        require(len(reviewers) == 1 and reviewers[0]["prevent_self_review"] is False and [(r["type"], r["reviewer"]["id"]) for r in reviewers[0]["reviewers"]] == [("User", 1100550)], "game_publication_review_policy")
    branches = metadata.github("/environments/game-publication/deployment-branch-policies")
    require(branches["total_count"] == len(branches["branch_policies"]) == 1 and [(b["name"], b["type"]) for b in branches["branch_policies"]] == [("main", "branch")], "game_publication_branch_policy")
    return environment


def publication_authority(info, env):
    require(env.get("GAME_PUBLICATION_OPERATION") == "publish" and env.get("EXPECTED_IMAGE_DIGEST") == info["image_digest"] and env.get("EXPECTED_ARCHIVE_SHA256") == info["archive_sha256"], "game_publication_not_approved")
    environment = publication_configuration(env)
    if env.get("GITHUB_EVENT_NAME") == "workflow_run":
        game_automation.push_ci(info["ci_run_id"], info["source_revision"], api=metadata.github)
    else:
        reviews = metadata.github(f"/actions/runs/{info['publication_run_id']}/approvals")
        selected = [review for review in reviews if any(item["id"] == environment["id"] and item["name"] == "game-publication" for item in review["environments"])]
        require(len(selected) == 1 and selected[0]["state"] == "approved" and selected[0]["user"]["id"] == 1100550, "game_publication_review_missing")


def reserve(info):
    name = "release-attempt/game-publication/" + info["source_revision"]
    rules = metadata.github("/rulesets?per_page=100")
    selected = [rule for rule in rules if rule["name"] == "Immutable release attempts" and rule["target"] == "tag" and rule["enforcement"] == "active"]
    require(len(selected) == 1, "game_attempt_rule_missing")
    rule = metadata.github("/rulesets/" + str(selected[0]["id"]))
    require(rule.get("enforcement") == "active" and rule.get("target") == "tag" and rule["conditions"]["ref_name"] == {"include": ["refs/tags/release-attempt/**"], "exclude": []} and {value["type"] for value in rule["rules"]} == {"update", "deletion"}, "game_attempt_rule_changed")
    if "current_user_can_bypass" in rule:
        require(rule["current_user_can_bypass"] == "never", "game_attempt_publisher_can_bypass")
    if "bypass_actors" in rule:
        require(rule["bypass_actors"] == [], "game_attempt_bypass_actors")
        verification = "visible_empty_actor_list"
    else:
        require(rule.get("current_user_can_bypass") == "never", "game_attempt_bypass_visibility")
        verification = "effective_never"
    require(metadata.github("/git/matching-refs/tags/" + name) == [], "game_attempt_already_reserved")
    def write(path, body):
        require(path in {"/git/tags", "/git/refs"}, "game_attempt_write_route")
        result = subprocess.run(["gh", "api", "--hostname", "github.com", "--method", "POST", "--input", "-", "repos/" + REPOSITORY + path], input=json.dumps(body).encode(), env=client_environment(), capture_output=True, timeout=45)
        require(result.returncode == 0 and len(result.stdout) <= 65536, "game_attempt_write_failed_no_retry")
        return json.loads(result.stdout, object_pairs_hook=metadata.unique_object)
    tag = write("/git/tags", {"tag": name, "message": json.dumps({"version": 1, **info, "ruleset_verification": verification}, sort_keys=True), "object": info["source_revision"], "type": "commit"})
    reference = write("/git/refs", {"ref": "refs/tags/" + name, "sha": tag["sha"]})
    require(reference["ref"] == "refs/tags/" + name and reference["object"]["sha"] == tag["sha"], "game_attempt_receipt")
    return name, verification


class Registry:
    def __init__(self, env):
        credential = env.get("GH_TOKEN", "")
        require(bool(credential), "game_registry_credential_missing")
        self.environment = {key: env[key] for key in ["PATH", "HOME", "SSL_CERT_FILE", "SSL_CERT_DIR"] if key in env}
        authorization = base64.b64encode(("scowalt:" + credential).encode()).decode()
        query = urllib.parse.urlencode({"service": "ghcr.io", "scope": "repository:scowalt/rngwars-game-releases:pull,push"})
        status, body = self.request("https://ghcr.io/token?" + query, "Basic " + authorization)
        require(status == 200, "game_registry_auth_http_" + str(status))
        response = json.loads(body, object_pairs_hook=metadata.unique_object)
        require(type(response.get("token")) is str and 0 < len(response["token"]) <= 65536, "game_registry_token")
        self.token = response["token"]
        directory = Path(env["DOCKER_CONFIG"])
        require(directory.is_absolute() and not directory.exists() and not directory.is_symlink(), "game_registry_auth_directory")
        directory.mkdir(mode=0o700)
        with (directory / ".game-publication-owner").open("x") as marker:
            marker.write(env["GITHUB_RUN_ID"] + "\n")
        self.auth = directory / "config.json"
        descriptor = os.open(self.auth, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump({"auths": {"ghcr.io": {"auth": authorization}}}, stream)

    def request(self, url, authorization):
        require(url.startswith("https://ghcr.io/"), "game_registry_origin")
        accept = "application/json" if url.startswith("https://ghcr.io/token?") else "application/vnd.oci.image.manifest.v1+json"
        configuration = ["silent", "show-error", 'proto = "=https"', "max-time = 45", "max-filesize = 2097152", "url = " + json.dumps(url), 'request = "GET"', "header = " + json.dumps("Authorization: " + authorization), "header = " + json.dumps("Accept: " + accept), 'write-out = "\\n%{http_code}"']
        result = subprocess.run(["curl", "-q", "--config", "-"], input=("\n".join(configuration) + "\n").encode(), env=self.environment, capture_output=True, timeout=55)
        require(result.returncode == 0 and len(result.stdout) <= 2 * 1024 * 1024 + 4, "game_registry_transport")
        body, separator, code = result.stdout.rpartition(b"\n")
        require(separator and re.fullmatch(rb"[1-5][0-9]{2}", code), "game_registry_status")
        return int(code), body

    def manifest(self, reference):
        require(re.fullmatch(r"[a-f0-9]{40}|sha256:[a-f0-9]{64}", reference), "game_registry_reference")
        return self.request("https://ghcr.io/v2/scowalt/rngwars-game-releases/manifests/" + reference, "Bearer " + self.token)

    def push(self, path, revision):
        environment = {**self.environment, "REGISTRY_AUTH_FILE": str(self.auth)}
        result = subprocess.run(["skopeo", "--override-os", "linux", "--override-arch", "arm64", "copy", "--preserve-digests", "--retry-times", "0", "oci-archive:" + str(path), "docker://" + IMAGE + ":" + revision], env=environment, capture_output=True, timeout=600)
        require(result.returncode == 0, "game_registry_push_failed_no_retry")

    def verify(self, info):
        status, body = self.manifest(info["source_revision"])
        require(status == 200 and "sha256:" + hashlib.sha256(body).hexdigest() == info["image_digest"], "game_registry_manifest_readback")
        manifest = json.loads(body, object_pairs_hook=metadata.unique_object)
        require(manifest["config"]["digest"] == info["config_digest"], "game_registry_config_binding")


def publish(info, destination, env):
    global OPERATION_STAGE
    OPERATION_STAGE = "review"
    publication_authority(info, env)
    OPERATION_STAGE = "registry_auth"
    registry = Registry(env)
    OPERATION_STAGE = "registry_lookup"
    status, _ = registry.manifest(info["source_revision"])
    require(status == 404, "game_registry_tag_not_absent_" + str(status))
    require(metadata.github("/git/ref/heads/main")["object"]["sha"] == info["source_revision"], "stale_game_publication")
    OPERATION_STAGE = "attempt_intent"
    with (Path(destination) / "publication-intent.json").open("x") as stream:
        json.dump(info, stream, sort_keys=True)
    OPERATION_STAGE = "attempt_reservation"
    attempt, rule_verification = reserve(info)
    OPERATION_STAGE = "registry_push"
    registry.push(Path(destination) / "image.oci.tar", info["source_revision"])
    OPERATION_STAGE = "registry_readback"
    registry.verify(info)
    return {**info, "status": "image_published_not_yet_attested", "image_repository": IMAGE, "attempt_tag": attempt, "ruleset_verification": rule_verification}


def verify_published(identity, receipt, env):
    receipt = Path(receipt)
    require(receipt.is_file() and not receipt.is_symlink() and 0 < receipt.stat().st_size <= 65536, "game_publication_receipt")
    info = json.loads(receipt.read_bytes(), object_pairs_hook=metadata.unique_object)
    require(all(info[key] == value for key, value in identity.items() if key != "status") and info["image_repository"] == IMAGE and info["status"] == "image_published_not_yet_attested", "game_publication_receipt_binding")
    require(re.fullmatch(r"sha256:[a-f0-9]{64}", info["image_digest"]), "game_published_digest")
    revision = identity["source_revision"]
    command = ["gh", "attestation", "verify", "oci://" + IMAGE + "@" + info["image_digest"], "--bundle-from-oci", "--hostname", "github.com", "--repo", REPOSITORY, "--cert-identity", "https://github.com/" + WORKFLOW, "--cert-oidc-issuer", "https://token.actions.githubusercontent.com", "--signer-digest", revision, "--source-digest", revision, "--source-ref", "refs/heads/main", "--deny-self-hosted-runners", "--predicate-type", "https://slsa.dev/provenance/v1", "--format", "json", "--limit", "30"]
    environment = {**client_environment(), "DOCKER_CONFIG": env["DOCKER_CONFIG"]}
    result = subprocess.run(command, env=environment, capture_output=True, timeout=120)
    require(result.returncode == 0 and 0 < len(result.stdout) <= 8 * 1024 * 1024, "game_attestation_verification")
    records = json.loads(result.stdout, object_pairs_hook=metadata.unique_object)
    require(type(records) is list and 0 < len(records) <= 30, "game_attestation_results")
    invocation = f"https://github.com/{REPOSITORY}/actions/runs/{identity['publication_run_id']}/attempts/1"
    for record in records:
        statement = record["verificationResult"]["statement"]
        if statement["predicateType"] == "https://slsa.dev/provenance/v1" and any(subject.get("digest", {}).get("sha256") == info["image_digest"].removeprefix("sha256:") for subject in statement["subject"]) and statement["predicate"].get("runDetails", {}).get("metadata", {}).get("invocationId") == invocation:
            return {**info, "status": "game_image_publication_verified"}
    raise Blocked("game_attestation_invocation")


def main():
    global OPERATION_STAGE
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("resolve")
    verifying = commands.add_parser("verify-published")
    verifying.add_argument("receipt")
    for name in ["prepare", "publish"]:
        receiving = commands.add_parser(name)
        receiving.add_argument("destination")
        receiving.add_argument("--artifact-id", required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_run" and args.command != "verify-published":
        revision, run_id, ci_run = context(os.environ)
        require(os.environ.get("GAME_AUTOMATIC_CD_ENABLED") == "true", "automatic_game_disabled")
        ci = metadata.github(f"/actions/runs/{ci_run}")
        if ci["head_sha"] != revision or metadata.github("/git/ref/heads/main")["object"]["sha"] != revision:
            if os.environ.get("GITHUB_OUTPUT"):
                output({"eligible": "false"})
            print(json.dumps({"status": "automatic_source_superseded", "source_revision": revision}))
            return
    if args.command == "verify-published" and os.environ.get("GITHUB_EVENT_NAME") == "workflow_run":
        revision, run_id, ci_run = context(os.environ)
        game_automation.push_ci(ci_run, revision, api=metadata.github, current=False)
        run = metadata.github(f"/actions/runs/{run_id}")
        require(run["id"] == run_id and run["head_sha"] == revision and run["event"] == "workflow_run" and run["status"] == "in_progress" and run["run_attempt"] == 1 and run["actor"]["id"] == run["triggering_actor"]["id"] == 1100550 and run["repository"]["id"] == run["head_repository"]["id"] == 1442331254 and run["path"] == ".github/workflows/game-publication.yml", "automatic_finalization_context")
        info = {"repository": REPOSITORY, "repository_id": 1442331254, "source_revision": revision, "source_branch": "main", "ci_run_id": ci_run, "workflow_revision": revision, "publication_run_id": run_id}
    else:
        info = resolve(os.environ)
    if args.command in {"prepare", "publish"}:
        OPERATION_STAGE = "candidate"
        info = prepare(info, identifier(args.artifact_id), args.destination)
    if args.command == "publish":
        info = publish(info, args.destination, os.environ)
    if args.command == "verify-published":
        OPERATION_STAGE = "attestation"
        info = verify_published(info, args.receipt, os.environ)
    OPERATION_STAGE = "outputs"
    if os.environ.get("GITHUB_OUTPUT"):
        values = {"source_revision": info["source_revision"], "eligible": "true"}
        if args.command in {"prepare", "publish"}:
            values.update(image_sha256=info["image_digest"].removeprefix("sha256:"), config_sha256=info["config_digest"].removeprefix("sha256:"), archive_sha256=info["archive_sha256"])
        output(values)
    print(json.dumps(info))


if __name__ == "__main__":
    try:
        main()
    except Blocked as error:
        print("Game publication blocked: " + str(error), file=sys.stderr)
        raise SystemExit(1)
    except Exception as error:
        kind = type(error).__name__
        if kind not in {"KeyError", "TypeError", "ValueError", "JSONDecodeError", "FileNotFoundError", "FileExistsError", "PermissionError", "TimeoutExpired", "OSError"}:
            kind = "unexpected_failure"
        print("Game publication blocked: " + OPERATION_STAGE + "_" + kind, file=sys.stderr)
        raise SystemExit(1)
