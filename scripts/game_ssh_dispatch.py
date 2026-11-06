import argparse
import json
import os
from pathlib import Path
import re
import resource
import signal
import socket
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import game_ssh_probe


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    args = parser.parse_args()
    if os.environ.get("SSH_ORIGINAL_COMMAND") == "rngwars-game-preflight-v1":
        sys.argv = [sys.argv[0]]
        return game_ssh_probe.main()
    signal.signal(signal.SIGALRM, game_ssh_probe.timed_out)
    signal.alarm(5)
    try:
        if os.environ.get("SSH_ORIGINAL_COMMAND") != "rngwars-game-deploy-v1" or sys.stdin.isatty():
            raise ValueError()
        raw = sys.stdin.buffer.read(8193)
        if not 0 < len(raw) <= 8192:
            raise ValueError()
        request = json.loads(raw, object_pairs_hook=game_ssh_probe.unique)
        if type(request) is not dict or set(request) != {"version", "run_id", "github_token"} or type(request["version"]) is not int or request["version"] != 1 or type(request["run_id"]) is not int or not 0 < request["run_id"] < 10 ** 20 or type(request["github_token"]) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{20,4096}", request["github_token"]):
            raise ValueError()
        path = Path(args.socket)
        if not path.is_absolute() or any(part.is_symlink() for part in (path, *path.parents)) or not stat.S_ISSOCK(path.stat().st_mode):
            raise ValueError()
        signal.alarm(915)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(905)
            connection.connect(str(path))
            connection.sendall(raw)
            connection.shutdown(socket.SHUT_WR)
            content = bytearray()
            while chunk := connection.recv(8193):
                content.extend(chunk)
                if len(content) > 8192:
                    raise ValueError()
        reply = json.loads(content, object_pairs_hook=game_ssh_probe.unique)
        deferred = type(reply) is dict and reply.get("status") == "deployment_deferred"
        fields = {"status", "run_id", "controller_revision", "image_digest", "source_revision", "publication_run_id"} | ({"retry_after_seconds"} if deferred else set())
        if type(reply) is not dict or set(reply) != fields or reply["run_id"] != request["run_id"] or reply["status"] not in {"game_deployed", "game_rolled_back", "deployment_blocked_before_live_change", "operator_recovery_required", "deployment_deferred"}:
            raise ValueError()
        if not all(type(reply[k]) is str and re.fullmatch(r"[a-f0-9]{40}", reply[k]) for k in ["controller_revision", "source_revision"]) or type(reply["image_digest"]) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", reply["image_digest"]) or type(reply["publication_run_id"]) is not int or not 0 < reply["publication_run_id"] < 10 ** 20:
            raise ValueError()
        if deferred and (type(reply["retry_after_seconds"]) is not int or not 1 <= reply["retry_after_seconds"] <= 1500):
            raise ValueError()
        print(json.dumps(reply, sort_keys=True))
        return 75 if deferred else 0 if reply["status"] == "game_deployed" else 1
    except Exception:
        print("Restricted game command rejected or outcome unconfirmed", file=sys.stderr)
        return 64
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
