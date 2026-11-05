import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile

from marketing_artifact import Blocked, require, unique_object


MEDIA = "application/vnd.oci.image."
MAX_ARCHIVE = 1024 * 1024 * 1024
MAX_JSON = 2 * 1024 * 1024
REPOSITORY = "scowalt/rngwars-game"
NATIVE_CHECKS = {"production_rejects_unmarked_empty_population", "offline_initialization_without_web_host", "offline_initialization_rejects_root", "encrypted_empty_baseline_backup_restore", "production_accepts_initialized_empty_restore", "native_SQLite_signup", "profile_update", "practice_creation", "production_restart_with_same_DB_and_token", "bundled_frontend", "distributed_legal_notices", "production_does_not_create_missing_DB", "multiplayer_sequential_join_completion"}


def inspect(path, revision):
    path = Path(path)
    require(re.fullmatch(r"[a-f0-9]{40}", revision) and path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_ARCHIVE, "artifact_input")
    with tarfile.open(path, "r:") as archive:
        entries = {}
        names = set()
        for member in archive:
            require(len(names) < 128, "OCI_entry_limit")
            require(member.name not in names, "duplicate_OCI_entry")
            names.add(member.name)
            if member.isdir() and member.name.rstrip("/") in {"blobs", "blobs/sha256"}:
                continue
            entries[member.name] = member
        archive.fileobj.seek(archive.offset)
        while chunk := archive.fileobj.read(1024 * 1024):
            require(not chunk.strip(b"\0"), "OCI_trailing_content")
        used = {"oci-layout", "index.json"}
        def document(name):
            entry = entries[name]
            require(entry.isfile() and 0 < entry.size <= MAX_JSON, "OCI_metadata_size")
            with archive.extractfile(entry) as stream:
                return json.loads(stream.read(), object_pairs_hook=unique_object)
        def blob(descriptor, media):
            require(type(descriptor) is dict and {"mediaType", "digest", "size"} <= set(descriptor) <= {"mediaType", "digest", "size", "annotations", "platform"}, "OCI_descriptor_fields")
            require(type(descriptor["size"]) is int and 0 < descriptor["size"] <= MAX_ARCHIVE, "OCI_descriptor_size")
            if "platform" in descriptor:
                require(descriptor["platform"].get("os") == "linux" and descriptor["platform"].get("architecture") == "arm64", "OCI_descriptor_platform")
            require(descriptor["mediaType"] == MEDIA + media and re.fullmatch(r"sha256:[a-f0-9]{64}", descriptor["digest"]), "OCI_descriptor")
            name = "blobs/sha256/" + descriptor["digest"].split(":")[1]
            entry = entries[name]
            used.add(name)
            require(entry.isfile() and entry.size == descriptor["size"], "OCI_blob_size")
            with archive.extractfile(entry) as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            require("sha256:" + digest == descriptor["digest"], "OCI_blob_digest")
            return name
        require(document("oci-layout") == {"imageLayoutVersion": "1.0.0"}, "OCI_layout")
        index = document("index.json")
        require(index["schemaVersion"] == 2 and len(index["manifests"]) == 1, "OCI_single_image_required")
        selected = index["manifests"][0]
        if selected["mediaType"] == MEDIA + "index.v1+json":
            nested = document(blob(selected, "index.v1+json"))
            require(nested["schemaVersion"] == 2 and nested["mediaType"] == MEDIA + "index.v1+json" and len(nested["manifests"]) == 1, "OCI_single_image_required")
            selected = nested["manifests"][0]
        manifest = document(blob(selected, "manifest.v1+json"))
        require(manifest["schemaVersion"] == 2 and manifest["mediaType"] == MEDIA + "manifest.v1+json", "OCI_manifest")
        config = document(blob(manifest["config"], "config.v1+json"))
        require(config["os"] == "linux" and config["architecture"] == "arm64", "native_ARM64_image_required")
        runtime = config["config"]
        require(runtime["User"] == "10001:10001" and runtime["Entrypoint"] == ["/app/game-entrypoint.sh"] and runtime["Cmd"] == ["dotnet", "RNGWars.Api.dll"], "game_runtime_identity")
        require(runtime["Labels"]["org.opencontainers.image.revision"] == revision and runtime["Labels"]["org.opencontainers.image.source"] == "https://github.com/" + REPOSITORY, "image_source_binding")
        layers = manifest["layers"]
        require(0 < len(layers) <= 64 and config["rootfs"]["type"] == "layers" and len(config["rootfs"]["diff_ids"]) == len(layers), "OCI_layers")
        for layer in layers:
            require(layer["mediaType"] in {MEDIA + "layer.v1.tar", MEDIA + "layer.v1.tar+gzip"}, "OCI_layer_media")
            blob(layer, layer["mediaType"].removeprefix(MEDIA))
        require(set(entries) == used, "unexpected_OCI_payload")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"status": "OCI_validated_not_release_approval", "revision": revision, "platform": "linux/arm64", "image_digest": selected["digest"], "config_digest": manifest["config"]["digest"], "archive_sha256": digest, "layers": len(layers)}


def verify_native(path, info):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 65536, "native_receipt_file")
    receipt = json.loads(path.read_bytes(), object_pairs_hook=unique_object)
    require(receipt["source_revision"] == info["revision"] and receipt["image_id"] == info["config_digest"] and receipt["native_runner_architecture"] == "aarch64" and receipt["image_architecture"] == "arm64", "native_receipt_identity")
    require(receipt["container_init"] is True and receipt["synthetic_data_only"] is True and all(receipt[key] is False for key in ["published_host_ports", "external_container_network", "production_host_access"]), "native_receipt_isolation")
    require(type(receipt["checks"]) is list and len(receipt["checks"]) == len(NATIVE_CHECKS) and set(receipt["checks"]) == NATIVE_CHECKS, "native_receipt_checks")
    return {**info, "native_receipt_consistent": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["inspect", "verify-native"])
    parser.add_argument("archive")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--native-receipt")
    args = parser.parse_args()
    info = inspect(args.archive, args.revision)
    if args.command == "verify-native":
        require(args.native_receipt is not None, "native_receipt_required")
        info = verify_native(args.native_receipt, info)
    else:
        require(args.native_receipt is None, "unexpected_native_receipt_argument")
    print(json.dumps(info))


if __name__ == "__main__":
    try:
        main()
    except Blocked as error:
        print("Game artifact blocked: " + str(error), file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        print("Game artifact blocked: invalid_OCI_or_local_failure", file=sys.stderr)
        raise SystemExit(1)
