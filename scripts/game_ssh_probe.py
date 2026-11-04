import json
import os
import re
import resource
import signal
import sys


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def timed_out(signum, frame):
    raise TimeoutError()


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    signal.signal(signal.SIGALRM, timed_out)
    signal.alarm(5)
    try:
        if len(sys.argv) != 1 or os.environ.get("SSH_ORIGINAL_COMMAND") != "rngwars-game-preflight-v1" or sys.stdin.isatty():
            raise ValueError("invocation")
        raw = sys.stdin.buffer.read(513)
        if len(raw) > 512:
            raise ValueError("size")
        request = json.loads(raw, object_pairs_hook=unique)
        if type(request) is not dict or set(request) != {"version", "challenge"} or type(request["version"]) is not int or request["version"] != 1 or type(request["challenge"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", request["challenge"]):
            raise ValueError("request")
        print(json.dumps({"version": 1, "challenge": request["challenge"], "status": "restricted_transport_only"}, sort_keys=True))
        return 0
    except Exception:
        print("Restricted SSH probe rejected", file=sys.stderr)
        return 64
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
