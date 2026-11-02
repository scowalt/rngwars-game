import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from datetime import datetime, timezone


class GateError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise GateError()


def require(condition):
    if not condition:
        raise GateError()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def read_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(65537)
    require(len(raw) <= 65536)
    return json.loads(raw, object_pairs_hook=unique)


def check(operation, policy, context, evidence, now=None):
    require(operation in {"marketing", "publish-game", "deploy-game"})
    require(type(policy) is dict and type(context) is dict and type(evidence) is dict)
    require(set(policy) == {"enabled", "operations", "repository", "repository_id", "owner", "ref", "environment", "image_repository", "platform", "required_checks"})
    require(type(policy.get("operations")) is list and all(value in {"marketing", "publish-game", "deploy-game"} for value in policy["operations"]))
    require(policy.get("enabled") is True and operation in policy["operations"])
    require(type(policy.get("owner")) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", policy["owner"]))
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", policy.get("repository", "")))
    require(re.fullmatch(r"[1-9][0-9]*", policy.get("repository_id", "")))
    require(context.get("repository") == policy["repository"] and context.get("repository_id") == policy["repository_id"])
    require(context.get("actor") == policy.get("owner") and context.get("triggering_actor") == policy.get("owner") and bool(policy.get("owner")))
    require(context.get("event_name") == "workflow_dispatch" and context.get("ref") == policy.get("ref"))
    require(policy.get("ref") in {"refs/heads/main", "refs/heads/production"})
    require(context.get("environment") == policy.get("environment") and bool(policy.get("environment")))
    require(type(context.get("run_attempt")) is int and context["run_attempt"] == 1)
    revision = context.get("sha", "")
    require(re.fullmatch(r"[a-f0-9]{40}", revision) and context.get("approved_revision") == revision)
    fence = context.get("private_fence_record")
    require(context.get("controller_fence_attested") is True and type(fence) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}", fence))
    require(evidence.get("revision") == revision and evidence.get("complete") is True)
    require(evidence.get("operation") == operation)
    timestamp = datetime.fromisoformat(evidence["verified_at"])
    require(timestamp.tzinfo is not None)
    age = ((now or datetime.now(timezone.utc)) - timestamp).total_seconds()
    require(0 <= age <= 86400)
    checks = evidence.get("checks")
    required = policy.get("required_checks")
    require(type(required) is list and len(required) > 0 and all(type(name) is str and name and name == name.strip() and not any(character in name for character in "\r\n\x00") for name in required))
    require(len(set(required)) == len(required))
    require(type(checks) is dict and set(checks) == set(required) and all(value == "passed" for value in checks.values()))
    require(re.fullmatch(r"[a-f0-9]{64}", evidence.get("artifact_sha256", "")))
    if operation == "marketing":
        require(context.get("approved_artifact_sha256") == evidence["artifact_sha256"])
    else:
        require(re.fullmatch(r"ghcr\.io/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*", policy.get("image_repository", "")))
        require(evidence.get("image_repository") == policy["image_repository"])
        require(policy.get("platform") in {"linux/amd64", "linux/arm64"} and evidence.get("platform") == policy["platform"])
        require(evidence.get("native_build") is True)
        if operation == "publish-game":
            require(context.get("tag_already_exists") is False)
        else:
            digest = evidence.get("published_digest", "")
            require(re.fullmatch(r"sha256:[a-f0-9]{64}", digest) and context.get("approved_digest") == digest)
            require(evidence.get("recovery_gates_complete") is True)
    return {"operation": operation, "revision": revision, "status": "context validated only; no operation performed"}


def main(argv=None):
    parser = Parser()
    parser.add_argument("operation", choices=["marketing", "publish-game", "deploy-game"])
    parser.add_argument("--policy", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--artifact", required=True)
    args = parser.parse_args(argv)
    evidence = read_json(args.evidence)
    with Path(args.artifact).open("rb") as artifact:
        actual = hashlib.file_digest(artifact, "sha256").hexdigest()
    require(actual == evidence.get("artifact_sha256"))
    result = check(args.operation, read_json(args.policy), read_json(args.context), evidence)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("release gate rejected; protected evidence requires review", file=sys.stderr)
        sys.exit(1)
