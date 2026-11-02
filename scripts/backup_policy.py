import json
import os
from pathlib import Path
import re
import stat


class PolicyError(Exception):
    pass


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError("backup policy rejected")
        result[key] = value
    return result


def absolute_path(value):
    path = Path(value)
    return path.is_absolute() and ".." not in path.parts


def validate_policy(value):
    fields = {"repository", "host", "tag", "image_repository", "data_directory"}
    if type(value) is not dict or set(value) != fields:
        raise PolicyError("backup policy rejected")
    if any(type(item) is not str or not item or item != item.strip() or any(character in item for character in "\r\n\x00") for item in value.values()):
        raise PolicyError("backup policy rejected")
    repository = value["repository"]
    remote = re.fullmatch(r"s3:https://[a-f0-9]{32}\.r2\.cloudflarestorage\.com/[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", repository)
    if not absolute_path(repository) and not remote:
        raise PolicyError("backup policy rejected")
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value[key]) for key in ("host", "tag")):
        raise PolicyError("backup policy rejected")
    if not re.fullmatch(r"ghcr\.io/[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*", value["image_repository"]):
        raise PolicyError("backup policy rejected")
    if not absolute_path(value["data_directory"]):
        raise PolicyError("backup policy rejected")
    return value


def load_policy(value):
    path = Path(value)
    if not absolute_path(value) or any(component.is_symlink() for component in (path, *path.parents)):
        raise PolicyError("backup policy rejected")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PolicyError("backup policy rejected")
        content = stream.read(65537)
    if len(content) > 65536:
        raise PolicyError("backup policy rejected")
    policy = validate_policy(json.loads(content, object_pairs_hook=unique))
    mode = stat.S_IMODE(info.st_mode)
    if policy["repository"].startswith("s3:"):
        parent = path.parent.stat()
        if info.st_uid != 0 or mode not in (0o400, 0o440) or parent.st_uid != 0 or stat.S_IMODE(parent.st_mode) not in (0o700, 0o750):
            raise PolicyError("remote backup policy requires trusted read-only installation")
        if any(component.stat().st_uid != 0 or stat.S_IMODE(component.stat().st_mode) & 0o022 for component in path.parents):
            raise PolicyError("remote backup policy requires trusted read-only installation")
    elif info.st_uid != os.geteuid() or mode != 0o600 or path.parent.stat().st_uid != os.geteuid() or stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
        raise PolicyError("local backup policy rejected")
    return policy
