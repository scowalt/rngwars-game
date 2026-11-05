import argparse
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import resource
import signal
import stat
import subprocess
import sys
import tempfile
import zipfile

from marketing_artifact import Blocked, require, resolve_ci, unique_object


REPOSITORY = "scowalt/rngwars-game"
MAX_REQUEST = 8192
MAX_METADATA = 2 * 1024 * 1024


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique_object)


def read_policy(value):
    path = Path(value)
    require(path.is_absolute() and not any(part.is_symlink() for part in (path, *path.parents)), "request_policy_path")
    for parent in path.parents:
        info = parent.stat()
        require(info.st_uid in {0, os.geteuid()} and not stat.S_IMODE(info.st_mode) & 0o022, "request_policy_parent")
    require(path.parent.stat().st_uid == os.geteuid() and stat.S_IMODE(path.parent.stat().st_mode) in {0o700, 0o750}, "request_policy_parent")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) in {0o400, 0o440} and 0 < info.st_size <= MAX_REQUEST, "request_policy_file")
        raw = stream.read(MAX_REQUEST + 1)
    require(len(raw) == info.st_size, "request_policy_changed")
    policy = decode(raw)
    require(type(policy) is dict and set(policy) == {"version", "environment_id", "workflow_blob", "ci_blob", "scripts_tree"}, "request_policy_shape")
    require(type(policy["version"]) is int and policy["version"] == 1 and type(policy["environment_id"]) is int and 0 < policy["environment_id"] < 10 ** 20, "request_policy_identity")
    require(all(type(policy[key]) is str and re.fullmatch(r"[a-f0-9]{40}", policy[key]) for key in ["workflow_blob", "ci_blob", "scripts_tree"]), "request_policy_contract")
    return policy


def fresh(value, limit):
    created = datetime.datetime.fromisoformat(value)
    require(created.tzinfo is not None and -300 <= (datetime.datetime.now(datetime.timezone.utc) - created).total_seconds() <= limit, "request_freshness")


def inspect(policy_path, envelope):
    require(type(envelope) is dict and set(envelope) == {"version", "run_id", "github_token"}, "request_envelope")
    require(type(envelope["version"]) is int and envelope["version"] == 1 and type(envelope["run_id"]) is int and 0 < envelope["run_id"] < 10 ** 20, "request_identity")
    token = envelope["github_token"]
    require(type(token) is str and re.fullmatch(r"[A-Za-z0-9_.-]{20,4096}", token), "request_credential")
    policy = read_policy(policy_path)
    run_id = envelope["run_id"]
    with tempfile.TemporaryDirectory(prefix="game-authority-") as directory:
        environment = {"PATH": os.environ.get("PATH", os.defpath), "HOME": directory, "GH_CONFIG_DIR": directory, "GH_TOKEN": token, "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
        def api(path, binary=False):
            result = subprocess.run(["gh", "api", "--hostname", "github.com", "--method", "GET", "repos/" + REPOSITORY + path], env=environment, capture_output=True, timeout=45)
            require(result.returncode == 0 and 0 < len(result.stdout) <= MAX_METADATA, "request_provider_unavailable")
            return result.stdout if binary else decode(result.stdout)
        run = api(f"/actions/runs/{run_id}")
        require(type(run["id"]) is int and run["id"] == run_id and type(run["run_attempt"]) is int and run["run_attempt"] == 1 and run["head_branch"] == "main" and run["status"] == "in_progress" and run["conclusion"] is None and run["event"] == "workflow_dispatch" and run["actor"]["id"] == run["triggering_actor"]["id"] == 1100550 and run["repository"]["id"] == run["head_repository"]["id"] == 1442331254, "request_run_identity")
        fresh(run["created_at"], 86400)
        revision = run["head_sha"]
        require(type(revision) is str and re.fullmatch(r"[a-f0-9]{40}", revision), "request_controller_revision")
        workflow = api("/actions/workflows/game-deployment.yml")
        require(workflow["state"] == "active" and workflow["id"] == run["workflow_id"] and workflow["path"] == run["path"] == ".github/workflows/game-deployment.yml", "request_workflow")
        require(api("/git/ref/heads/main")["object"]["sha"] == revision, "request_stale_controller")
        for filename, field in [("game-deployment.yml", "workflow_blob"), ("ci.yml", "ci_blob")]:
            file = api("/contents/.github/workflows/" + filename + "?ref=" + revision)
            require(file["type"] == "file" and file["sha"] == policy[field], "request_controller_contract")
        tree = api("/git/trees/" + revision)
        scripts = [item for item in tree["tree"] if item["path"] == "scripts"]
        require(tree["truncated"] is False and len(scripts) == 1 and scripts[0]["type"] == "tree" and scripts[0]["mode"] == "040000" and scripts[0]["sha"] == policy["scripts_tree"], "request_controller_contract")
        protected = api("/environments/game-production")
        require(type(protected["id"]) is int and protected["id"] == policy["environment_id"] and protected["name"] == "game-production" and protected["can_admins_bypass"] is False and protected["deployment_branch_policy"] == {"protected_branches": False, "custom_branch_policies": True}, "request_environment")
        reviewers = [rule for rule in protected["protection_rules"] if rule["type"] == "required_reviewers"]
        require(len(reviewers) == 1 and reviewers[0]["prevent_self_review"] is False and [(item["type"], item["reviewer"]["id"]) for item in reviewers[0]["reviewers"]] == [("User", 1100550)], "request_environment_reviewer")
        branches = api("/environments/game-production/deployment-branch-policies")
        require(branches["total_count"] == len(branches["branch_policies"]) == 1 and [(item["name"], item["type"]) for item in branches["branch_policies"]] == [("main", "branch")], "request_environment_branches")
        inventory = api(f"/actions/runs/{run_id}/attempts/1/jobs?per_page=100")
        expected = {"resolve": ("completed", "success"), "Private transport preflight": ("completed", "skipped"), "Deploy verified game release": ("in_progress", None)}
        require(inventory["total_count"] == len(inventory["jobs"]) == 3 and {job["name"] for job in inventory["jobs"]} == set(expected), "request_jobs")
        require(all(job["run_id"] == run_id and (job["status"], job["conclusion"]) == expected[job["name"]] and job["labels"] == ["ubuntu-24.04"] for job in inventory["jobs"]), "request_jobs")
        started = next(job["started_at"] for job in inventory["jobs"] if job["name"] == "Deploy verified game release")
        fresh(started, 1800)
        reviews = api(f"/actions/runs/{run_id}/approvals")
        require(len(reviews) == 1 and reviews[0]["state"] == "approved" and reviews[0]["user"]["id"] == 1100550 and [(item["id"], item["name"]) for item in reviews[0]["environments"]] == [(policy["environment_id"], "game-production")], "request_review")
        inventory = api(f"/actions/runs/{run_id}/artifacts?per_page=100")
        require(inventory["total_count"] == len(inventory["artifacts"]) <= 100, "request_artifact_inventory")
        matches = [item for item in inventory["artifacts"] if item["name"] == f"game-deployment-request-{run_id}-1"]
        require(len(matches) == 1, "request_artifact_inventory")
        artifact = matches[0]
        require(type(artifact["id"]) is int and 0 < artifact["id"] < 10 ** 20 and artifact["expired"] is False and type(artifact["size_in_bytes"]) is int and 0 < artifact["size_in_bytes"] <= MAX_METADATA, "request_artifact_identity")
        created = datetime.datetime.fromisoformat(artifact["created_at"])
        updated = datetime.datetime.fromisoformat(artifact["updated_at"])
        require(created.tzinfo is not None and updated.tzinfo is not None and datetime.datetime.fromisoformat(run["created_at"]) <= created <= updated <= datetime.datetime.fromisoformat(started), "request_artifact_timing")
        source = artifact["workflow_run"]
        require(source["id"] == run_id and source["repository_id"] == source["head_repository_id"] == 1442331254 and source["head_sha"] == revision and source["head_branch"] == "main", "request_artifact_source")
        raw = api(f"/actions/artifacts/{artifact['id']}/zip", binary=True)
        require("sha256:" + hashlib.sha256(raw).hexdigest() == artifact["digest"], "request_artifact_digest")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            require(len(entries) == 1 and entries[0].filename == entries[0].orig_filename == "request.json" and stat.S_IFMT(entries[0].external_attr >> 16) == stat.S_IFREG and not entries[0].flag_bits & 1 and entries[0].compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED} and 0 < entries[0].file_size <= MAX_REQUEST, "request_archive")
            request = decode(archive.read(entries[0]))
        require(type(request) is dict and set(request) == {"version", "operation", "run_id", "controller_revision", "ci_run_id", "image_source_revision", "image_digest", "publication_run_id"}, "request_shape")
        require(type(request["version"]) is int and request["version"] == 1 and request["operation"] == "deploy" and request["run_id"] == run_id and request["controller_revision"] == run["head_sha"], "request_binding")
        require(all(type(request[key]) is int and 0 < request[key] < 10 ** 20 for key in ["run_id", "ci_run_id", "publication_run_id"]), "request_run_identifiers")
        require(type(request["image_source_revision"]) is str and re.fullmatch(r"[a-f0-9]{40}", request["image_source_revision"]) and type(request["image_digest"]) is str and re.fullmatch(r"sha256:[a-f0-9]{64}", request["image_digest"]), "request_image_identity")
        ci_id = request["ci_run_id"]
        identity = resolve_ci(ci_id, revision, api=api)
        require(identity["source_revision"] == revision and identity["source_branch"] == "main", "request_CI_source")
        fresh(api(f"/actions/runs/{ci_id}")["created_at"], 86400)
        ci_jobs = api(f"/actions/runs/{ci_id}/attempts/1/jobs?per_page=100")
        require(ci_jobs["total_count"] == len(ci_jobs["jobs"]) == 3 and all(job["run_id"] == ci_id and job["labels"] == ["ubuntu-latest"] for job in ci_jobs["jobs"]), "request_CI_runner")
        require(api(f"/actions/runs/{run_id}")["status"] == "in_progress" and api(f"/actions/runs/{run_id}/approvals") == reviews, "request_authority_changed")
        latest_jobs = api(f"/actions/runs/{run_id}/attempts/1/jobs?per_page=100")
        require(latest_jobs["total_count"] == len(latest_jobs["jobs"]) == 3 and {job["name"] for job in latest_jobs["jobs"]} == set(expected) and all(job["run_id"] == run_id and (job["status"], job["conclusion"]) == expected[job["name"]] and job["labels"] == ["ubuntu-24.04"] for job in latest_jobs["jobs"]), "request_authority_changed")
        require(api("/git/ref/heads/main")["object"]["sha"] == revision, "request_stale_controller")
        return {"status": "reviewed_deployment_request_verified_no_execution", "request": request, "artifact_id": artifact["id"]}


def timed_out(signum, frame):
    raise Blocked("request_timeout")


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["inspect"])
    parser.add_argument("--policy", required=True)
    args = parser.parse_args()
    try:
        signal.signal(signal.SIGALRM, timed_out)
        signal.alarm(5)
        raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
        require(0 < len(raw) <= MAX_REQUEST, "request_size")
        signal.alarm(180)
        print(json.dumps(inspect(args.policy, decode(raw)), sort_keys=True))
        return 0
    except Blocked as error:
        print("Game deployment request blocked: " + str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Game deployment request blocked: invalid_or_unavailable_evidence", file=sys.stderr)
        return 1
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
