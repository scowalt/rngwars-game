import argparse
import datetime
import hashlib
import io
import json
import os
import re
import resource
import stat
import subprocess
import sys
import zipfile

import marketing_artifact as metadata
from marketing_artifact import Blocked, require, unique_object


REPOSITORY = "scowalt/rngwars-game"
IMAGE = "ghcr.io/scowalt/rngwars-game-releases"
MAX_METADATA = 2 * 1024 * 1024


def github(path, binary=False):
    environment = {key: os.environ[key] for key in ["PATH", "HOME", "GH_TOKEN", "GITHUB_TOKEN"] if key in os.environ}
    result = subprocess.run(["gh", "api", "--hostname", "github.com", "--method", "GET", "repos/" + REPOSITORY + path], env=environment, capture_output=True, timeout=45)
    require(result.returncode == 0 and 0 < len(result.stdout) <= MAX_METADATA, "automatic_provider_unavailable")
    return result.stdout if binary else json.loads(result.stdout, object_pairs_hook=unique_object)


def push_ci(run_id, revision, api=github, current=True):
    require(type(run_id) is int and 0 < run_id < 10 ** 20 and type(revision) is str and re.fullmatch(r"[a-f0-9]{40}", revision), "automatic_CI_input")
    run = api(f"/actions/runs/{run_id}")
    require(run["event"] == "push" and run["actor"]["id"] == run["triggering_actor"]["id"] == 1100550, "automatic_main_push_actor")
    created = datetime.datetime.fromisoformat(run["created_at"])
    require(created.tzinfo is not None and -300 <= (datetime.datetime.now(datetime.timezone.utc) - created).total_seconds() <= 86400, "automatic_CI_freshness")
    require(run["id"] == run_id and run["repository"]["id"] == run["head_repository"]["id"] == 1442331254 and run["head_sha"] == revision and run["head_branch"] == "main" and type(run["run_attempt"]) is int and run["run_attempt"] == 1 and run["status"] == "completed" and run["conclusion"] == "success", "automatic_CI_identity")
    workflow = api("/actions/workflows/ci.yml")
    require(workflow["id"] == run["workflow_id"] and workflow["state"] == "active" and workflow["path"] == run["path"] == ".github/workflows/ci.yml", "automatic_CI_workflow")
    if current:
        identity = metadata.resolve_ci(run_id, revision, api=api)
        require(identity["source_revision"] == revision and identity["source_branch"] == "main", "automatic_CI_source")
    jobs = api(f"/actions/runs/{run_id}/attempts/1/jobs?per_page=100")
    require(jobs["total_count"] == len(jobs["jobs"]) == 3 and {job["name"] for job in jobs["jobs"]} == {"Build API (F#)", "Build Frontend (SolidJS)", "Portable SQLite backup and deployment preparation"} and all(job["run_id"] == run_id and job["labels"] == ["ubuntu-latest"] and job["status"] == "completed" and job["conclusion"] == "success" for job in jobs["jobs"]), "automatic_CI_runners")
    return {"status": "trusted_main_push_CI", "source_revision": revision, "ci_run_id": run_id}


def publication(run_id, revision, api=github):
    require(type(run_id) is int and 0 < run_id < 10 ** 20 and type(revision) is str and re.fullmatch(r"[a-f0-9]{40}", revision), "automatic_publication_input")
    run = api(f"/actions/runs/{run_id}")
    workflow = api("/actions/workflows/game-publication.yml")
    require(run["id"] == run_id and run["workflow_id"] == workflow["id"] and workflow["state"] == "active" and workflow["path"] == run["path"] == ".github/workflows/game-publication.yml", "automatic_publisher_workflow")
    require(run["repository"]["id"] == run["head_repository"]["id"] == 1442331254 and run["head_sha"] == revision and run["head_branch"] == "main" and run["event"] == "workflow_run" and type(run["run_attempt"]) is int and run["run_attempt"] == 1 and run["actor"]["id"] == run["triggering_actor"]["id"] == 1100550 and run["status"] == "completed" and run["conclusion"] == "success", "automatic_publisher_identity")
    jobs = api(f"/actions/runs/{run_id}/attempts/1/jobs?per_page=100")
    require(jobs["total_count"] == len(jobs["jobs"]) == 4 and {job["name"] for job in jobs["jobs"]} == {"resolve", "Build and exercise native image", "prepare", "publish"}, "automatic_publisher_jobs")
    require(all(job["run_id"] == run_id and job["status"] == "completed" and job["conclusion"] == "success" and job["labels"] == ["ubuntu-24.04-arm" if job["name"] == "Build and exercise native image" else "ubuntu-24.04"] for job in jobs["jobs"]), "automatic_publisher_jobs")
    inventory = api(f"/actions/runs/{run_id}/artifacts?per_page=100")
    require(inventory["total_count"] == len(inventory["artifacts"]) <= 100, "automatic_receipt_inventory")
    matches = [item for item in inventory["artifacts"] if item["name"] == f"game-publication-{run_id}-1"]
    require(len(matches) == 1, "automatic_receipt_inventory")
    artifact = matches[0]
    require(type(artifact["id"]) is int and 0 < artifact["id"] < 10 ** 20 and artifact["expired"] is False and type(artifact["size_in_bytes"]) is int and 0 < artifact["size_in_bytes"] <= 65536, "automatic_receipt_identity")
    source = artifact["workflow_run"]
    require(source["id"] == run_id and source["repository_id"] == source["head_repository_id"] == 1442331254 and source["head_sha"] == revision and source["head_branch"] == "main", "automatic_receipt_source")
    raw = api(f"/actions/artifacts/{artifact['id']}/zip", binary=True)
    require(len(raw) <= 65536 and "sha256:" + hashlib.sha256(raw).hexdigest() == artifact["digest"], "automatic_receipt_digest")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) == 1, "automatic_receipt_archive")
        entry = entries[0]
        require(entry.filename == entry.orig_filename == "game-publication-verified.json" and stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFREG and not entry.flag_bits & 1 and entry.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED} and 0 < entry.file_size <= 8192, "automatic_receipt_archive")
        receipt = json.loads(archive.read(entry), object_pairs_hook=unique_object)
    require(receipt["status"] == "game_image_publication_verified" and receipt["repository"] == REPOSITORY and receipt["repository_id"] == 1442331254 and receipt["publication_run_id"] == run_id and receipt["source_revision"] == receipt["workflow_revision"] == receipt["revision"] == revision and receipt["source_branch"] == "main" and receipt["platform"] == "linux/arm64" and receipt["image_repository"] == IMAGE and receipt["native_receipt_consistent"] is True, "automatic_receipt_binding")
    require(all(type(receipt[k]) is str and re.fullmatch(r"sha256:[a-f0-9]{64}", receipt[k]) for k in ["image_digest", "config_digest"]) and receipt["attempt_tag"] == "release-attempt/game-publication/" + revision and receipt["ruleset_verification"] in {"effective_never", "visible_empty_actor_list"}, "automatic_receipt_release")
    push_ci(receipt["ci_run_id"], revision, api=api)
    return {"status": "trusted_automatic_release", "controller_revision": revision, "ci_run_id": receipt["ci_run_id"], "image_source_revision": revision, "image_digest": receipt["image_digest"], "publication_run_id": run_id}


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["ci", "publication"])
    parser.add_argument("--run", required=True, type=int)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    try:
        action = push_ci if args.operation == "ci" else publication
        print(json.dumps(action(args.run, args.revision), sort_keys=True))
        return 0
    except Blocked as error:
        print("Automatic game delivery blocked: " + str(error), file=sys.stderr)
        return 1
    except Exception:
        print("Automatic game delivery blocked: invalid_or_unavailable_evidence", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
