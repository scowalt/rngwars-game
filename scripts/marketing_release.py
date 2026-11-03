import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import cloudflare_static as cf
import marketing_artifact as m
import marketing_producer as producer


REPO = "scowalt/rngwars-game"
WORKFLOW = REPO + "/.github/workflows/marketing-release.yml@refs/heads/main"


def context(env):
    m.require(env.get("GITHUB_REPOSITORY_ID") == "1442331254" and env.get("GITHUB_REPOSITORY") == REPO and env.get("GITHUB_REF") == "refs/heads/main" and env.get("GITHUB_WORKFLOW_REF") == WORKFLOW and env.get("GITHUB_RUN_ATTEMPT") == "1" and env.get("GITHUB_EVENT_NAME") in {"workflow_run", "workflow_dispatch"}, "release_context")
    revision = env.get("GITHUB_WORKFLOW_SHA", "")
    m.require(re.fullmatch(r"[a-f0-9]{40}", revision), "release_revision")
    return revision, producer.identifier(env.get("GITHUB_RUN_ID", ""))


def candidate(run_id, revision, artifact_id=None):
    workflow = m.github("/actions/workflows/marketing-artifact.yml")
    run = m.github(f"/actions/runs/{run_id}")
    m.require(run["workflow_id"] == workflow["id"] and run["path"] == ".github/workflows/marketing-artifact.yml" and run["head_sha"] == revision and run["head_branch"] == "main", "producer_workflow_identity")
    m.require(run["status"] == "completed" and run["conclusion"] == "success" and run["run_attempt"] == 1 and run["event"] in {"workflow_run", "workflow_dispatch"} and run["repository"]["id"] == 1442331254 and run["head_repository"]["id"] == 1442331254, "producer_result")
    listing = m.github(f"/actions/runs/{run_id}/artifacts?per_page=100")
    m.require(listing["total_count"] == len(listing["artifacts"]) < 100, "artifact_inventory")
    matches = [a for a in listing["artifacts"] if a["name"] == f"marketing-release-{run_id}-1" and (artifact_id is None or a["id"] == artifact_id)]
    m.require(len(matches) == 1, "artifact_selection")
    artifact = matches[0]
    relation = artifact["workflow_run"]
    m.require(relation["id"] == run_id and relation["repository_id"] == 1442331254 and relation["head_repository_id"] == 1442331254 and relation["head_sha"] == revision and artifact["expired"] is False and 0 < artifact["size_in_bytes"] <= m.MAX_ARCHIVE, "artifact_identity")
    raw = producer.download(artifact["id"])
    m.require(artifact["digest"] == "sha256:" + hashlib.sha256(raw).hexdigest(), "artifact_transport_digest")
    bundle = producer.single_file(raw, "release.zip")
    manifest, files = m.inspect_bundle(bundle)
    identity = manifest["identity"]
    m.require(identity["producer_run_id"] == run_id and identity["workflow_revision"] == revision, "signed_identity")
    expected = {**m.resolve_ci(identity["ci_run_id"], revision), "producer_run_id": run_id}
    m.require(identity == expected, "source_identity")
    digest = producer.verify_signature(bundle, revision, run_id)
    kind = "production" if identity["source_branch"] == "main" else "preview"
    return {"artifact_id": artifact["id"], "producer_run_id": run_id, "source_revision": identity["source_revision"], "source_branch": identity["source_branch"], "bundle_sha256": digest, "kind": kind}, files


def github_write(path, body):
    m.require(path in {"/git/tags", "/git/refs"}, "github_write_route")
    request = urllib.request.Request("https://api.github.com/repos/" + REPO + path, data=json.dumps(body).encode(), headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json", "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), cf.NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            m.require(response.status == 201, "attempt_reservation_status")
            return json.loads(response.read(1024 * 1024))
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        raise m.Blocked("attempt_reservation_http_" + str(code)) from None


def reserve(info, revision, run_id):
    name = "release-attempt/marketing/" + info["kind"] + "/" + info["bundle_sha256"]
    rules = m.github("/rulesets?per_page=100")
    matches = [r for r in rules if r["name"] == "Immutable release attempts" and r["target"] == "tag" and r["enforcement"] == "active"]
    m.require(len(matches) == 1, "attempt_rule_missing")
    rule = m.github("/rulesets/" + str(matches[0]["id"]))
    m.require(rule["conditions"]["ref_name"] == {"include": ["refs/tags/release-attempt/**"], "exclude": []} and {r["type"] for r in rule["rules"]} == {"update", "deletion"} and not rule.get("bypass_actors"), "attempt_rule_changed")
    tag = github_write("/git/tags", {"tag": name, "message": json.dumps({"version": 1, "release_run_id": run_id, **info}, sort_keys=True), "object": revision, "type": "commit"})
    ref = github_write("/git/refs", {"ref": "refs/tags/" + name, "sha": tag["sha"]})
    m.require(ref["ref"] == "refs/tags/" + name and ref["object"]["sha"] == tag["sha"], "attempt_reservation_readback")
    return name


def evidence(binding, info, run_id, phase, record, secrets):
    raw = json.dumps(record)
    for secret in secrets:
        if secret:
            raw = raw.replace(secret, "<redacted>")
    payload = {"endpoint": binding["storage_endpoint"], "bucket": binding["storage_bucket"], "access_key": os.environ["RELEASE_STORAGE_ACCESS_KEY_ID"], "secret_key": os.environ["RELEASE_STORAGE_SECRET_ACCESS_KEY"], "encryption_key": os.environ["RELEASE_LOG_ENCRYPTION_KEY"], "phase": phase, "context": {"repository_id": 1442331254, "run_id": str(run_id), "artifact_sha256": info["bundle_sha256"], "kind": info["kind"]}, "record": json.loads(raw)}
    env = {k: os.environ[k] for k in ["PATH", "HOME", "LANG"] if k in os.environ}
    result = subprocess.run(["bun", str(Path(__file__).with_name("release_evidence.ts"))], input=json.dumps(payload).encode(), env=env, capture_output=True, timeout=45)
    m.require(result.returncode == 0, "private_evidence_unavailable")
    m.require(json.loads(result.stdout)["status"] == "private_evidence_retained", "private_evidence_receipt")


def health(origin, files, required=True):
    parsed = urllib.parse.urlsplit(origin)
    m.require(parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment, "health_origin")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), cf.NoRedirect())
    results = []
    paths = [("", files["index.html"])]
    paths.extend((name, content) for name, content in files.items() if name not in {"index.html", "404.html", "_headers", "_redirects"} and not name.endswith(".html"))
    for name, content in paths:
        url = origin.rstrip("/") + "/" + urllib.parse.quote(name, safe="/._-")
        request = urllib.request.Request(url, headers={"User-Agent": "RNGWars-migration-health-read", "Cache-Control": "no-cache"}, method="GET")
        try:
            with opener.open(request, timeout=20) as response:
                body = response.read(m.MAX_FILE + 1)
                references = re.findall(rb"/_astro/[A-Za-z0-9._/-]+\.(?:js|css)", content) if not name else []
                matched = body == content if name else (b"RNGWars" in body and (not required or all(path in body for path in references)))
                results.append({"path": name or "/", "status": response.status, "matched": matched, "bytes": len(body)})
        except urllib.error.HTTPError as error:
            results.append({"path": name or "/", "status": error.code, "matched": False})
            error.close()
        if not required:
            break
    return {"passed": bool(results) and all(x["status"] == 200 and x["matched"] for x in results), "checks": results}


def deploy(info, files, revision, run_id, binding):
    m.require(os.environ.get("MARKETING_RELEASE_ENABLED") == "true" and os.environ.get("RELEASE_KIND") == info["kind"], "release_not_enabled")
    client = cf.Client(binding["account_id"], binding["worker_name"], os.environ["CLOUDFLARE_API_TOKEN"])
    secrets = client.secrets + [os.environ[k] for k in ["RELEASE_STORAGE_ACCESS_KEY_ID", "RELEASE_STORAGE_SECRET_ACCESS_KEY", "RELEASE_LOG_ENCRYPTION_KEY", "GH_TOKEN"]]
    baseline = None
    version = None
    promoted = False
    try:
        cf.fenced(client, binding)
        baseline = cf.active_version(client)
        m.require(health(binding["health_origin"], files, required=False)["passed"], "baseline_health_unavailable")
        evidence(binding, info, run_id, "intent", {"binding": binding, "baseline_version": baseline, "candidate": info, "events": client.events}, secrets)
        reserve(info, revision, run_id)
        version = cf.upload(client, binding, files, run_id, info["source_revision"], info["bundle_sha256"])
        evidence(binding, info, run_id, "uploaded", {"version_id": version, "baseline_version": baseline, "events": client.events}, secrets + client.secrets)
        m.require(cf.active_version(client) == baseline, "production_changed_during_upload")
        if info["kind"] == "production":
            cf.fenced(client, binding)
            try:
                cf.promote(client, version)
            except m.Blocked:
                raise
            except Exception:
                m.require(cf.active_version(client) == version, "ambiguous_promotion_no_retry")
            promoted = True
            m.require(cf.active_version(client) == version, "deployment_readback")
            result = None
            for attempt in range(5):
                result = health(binding["health_origin"], files)
                if result["passed"]:
                    break
                time.sleep(3)
            m.require(result is not None and result["passed"], "deployment_health")
        else:
            observed = client.request("GET", f"/workers/scripts/{client.worker}/versions/{version}")
            m.require(observed["id"] == version and cf.active_version(client) == baseline, "preview_version_readback")
            serving = client.request("GET", f"/workers/scripts/{client.worker}/subdomain")
            if serving.get("previews_enabled") is True:
                subdomain = client.request("GET", "/workers/subdomain")["subdomain"]
                m.require(re.fullmatch(r"[a-z0-9-]+", subdomain), "preview_subdomain")
                origin = f"https://{version.split('-')[0]}-{client.worker}.{subdomain}.workers.dev"
                result = health(origin, files)
                m.require(result["passed"], "preview_health")
            else:
                m.require(serving.get("previews_enabled") is False, "preview_serving_unknown")
                result = {"passed": True, "method": "version_metadata", "preview_urls_preserved_disabled": True}
        evidence(binding, info, run_id, "verified", {"version_id": version, "baseline_version": baseline, "health": result, "events": client.events}, secrets + client.secrets)
        print(json.dumps({"status": "release_verified", "kind": info["kind"], "source_revision": info["source_revision"], "bundle_sha256": info["bundle_sha256"]}))
    except Exception as error:
        rollback = None
        if promoted and baseline and version:
            try:
                if cf.active_version(client) == version:
                    cf.promote(client, baseline)
                    rollback = cf.active_version(client) == baseline and health(binding["health_origin"], files, required=False)["passed"]
            except Exception:
                rollback = "unconfirmed"
        try:
            evidence(binding, info, run_id, "failed", {"error_code": str(error) if isinstance(error, m.Blocked) else type(error).__name__, "version_id": version, "baseline_version": baseline, "rollback": rollback, "events": client.events}, secrets + client.secrets)
        except Exception:
            pass
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "preflight", "deploy"])
    args = parser.parse_args()
    revision, run_id = context(os.environ)
    producer_run = producer.identifier(os.environ.get("PRODUCER_RUN_ID", ""))
    selected = os.environ.get("RELEASE_ARTIFACT_ID")
    info, files = candidate(producer_run, revision, producer.identifier(selected) if selected else None)
    if args.command == "prepare":
        producer.output({key: str(info[key]) for key in ["artifact_id", "producer_run_id", "source_revision", "bundle_sha256", "kind"]})
        print(json.dumps({"status": "candidate_verified_no_deployment", **info}))
    else:
        m.require(os.environ.get("EXPECTED_BUNDLE_SHA256") == info["bundle_sha256"], "approved_bundle_changed")
        binding = json.loads(os.environ["MARKETING_RELEASE_BINDINGS"])
        m.require(binding["schema"] == 1 and binding["storage_endpoint"] == "https://" + binding["account_id"] + ".r2.cloudflarestorage.com" and len(binding["native_trigger_ids"]) == 2 and len(set(binding["native_trigger_ids"])) == 2, "release_binding")
        if args.command == "preflight":
            client = cf.Client(binding["account_id"], binding["worker_name"], os.environ["CLOUDFLARE_API_TOKEN"])
            cf.inspect_worker(client, binding)
            current = cf.active_version(client)
            protected = client.secrets + [os.environ[k] for k in ["RELEASE_STORAGE_ACCESS_KEY_ID", "RELEASE_STORAGE_SECRET_ACCESS_KEY", "RELEASE_LOG_ENCRYPTION_KEY", "GH_TOKEN"]]
            evidence(binding, info, run_id, "preflight", {"binding": binding, "active_version": current, "events": client.events, "provider_mutations": 0}, protected)
            print(json.dumps({"status": "release_credentials_preflight_verified_no_provider_mutation", "source_revision": info["source_revision"], "bundle_sha256": info["bundle_sha256"]}))
        else:
            deploy(info, files, revision, run_id, binding)


if __name__ == "__main__":
    try:
        main()
    except m.Blocked as error:
        print("Marketing release blocked: " + str(error), file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        print("Marketing release stopped; detailed evidence is private", file=sys.stderr)
        raise SystemExit(1)
