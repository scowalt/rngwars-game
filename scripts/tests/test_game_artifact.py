import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest


TOOL = Path(__file__).parents[1] / "game_artifact.py"
REVISION = "a" * 40
MEDIA = "application/vnd.oci.image."


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def fixture(architecture="arm64", user="10001:10001", revision=REVISION):
    layer_buffer = io.BytesIO()
    with tarfile.open(fileobj=layer_buffer, mode="w", format=tarfile.USTAR_FORMAT) as layer:
        entry = tarfile.TarInfo("fixture.txt")
        data = b"disposable native image fixture\n"
        entry.size = len(data)
        layer.addfile(entry, io.BytesIO(data))
    layer = layer_buffer.getvalue()
    files = {"oci-layout": encoded({"imageLayoutVersion": "1.0.0"})}
    def blob(data, media):
        digest = hashlib.sha256(data).hexdigest()
        files["blobs/sha256/" + digest] = data
        return {"mediaType": MEDIA + media, "digest": "sha256:" + digest, "size": len(data)}
    layer_descriptor = blob(layer, "layer.v1.tar")
    config = {"architecture": architecture, "os": "linux", "rootfs": {"type": "layers", "diff_ids": [layer_descriptor["digest"]]}, "config": {"User": user, "Entrypoint": ["/app/game-entrypoint.sh"], "Cmd": ["dotnet", "RNGWars.Api.dll"], "Labels": {"org.opencontainers.image.revision": revision, "org.opencontainers.image.source": "https://github.com/scowalt/rngwars-game"}}}
    configuration = blob(encoded(config), "config.v1+json")
    manifest = blob(encoded({"schemaVersion": 2, "mediaType": MEDIA + "manifest.v1+json", "config": configuration, "layers": [layer_descriptor]}), "manifest.v1+json")
    files["index.json"] = encoded({"schemaVersion": 2, "manifests": [manifest]})
    return files


def archive(files, extra=()):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as output:
        for name, data in [*sorted(files.items()), *extra]:
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            output.addfile(entry, io.BytesIO(data))
    return buffer.getvalue()


class GameArtifactTests(unittest.TestCase):
    def invoke(self, raw, revision=REVISION):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.tar"
            path.write_bytes(raw)
            return subprocess.run([sys.executable, str(TOOL), "inspect", str(path), "--revision", revision], capture_output=True, text=True, timeout=15)

    def test_binds_native_receipt_to_the_actual_image_config(self):
        files = fixture()
        manifest = json.loads(files["blobs/sha256/" + json.loads(files["index.json"])["manifests"][0]["digest"].split(":")[1]])
        receipt = {"source_revision": REVISION, "image_id": manifest["config"]["digest"], "native_runner_architecture": "aarch64", "image_architecture": "arm64", "container_init": True, "checks": ["production_rejects_unmarked_empty_population", "offline_initialization_without_web_host", "offline_initialization_rejects_root", "encrypted_empty_baseline_backup_restore", "production_accepts_initialized_empty_restore", "native_SQLite_signup", "profile_update", "practice_creation", "production_restart_with_same_DB_and_token", "bundled_frontend", "distributed_legal_notices", "production_does_not_create_missing_DB", "multiplayer_sequential_join_completion"], "synthetic_data_only": True, "published_host_ports": False, "external_container_network": False, "production_host_access": False}
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.tar"
            image.write_bytes(archive(files))
            proof = Path(directory) / "native.json"
            proof.write_text(json.dumps(receipt))
            command = [sys.executable, str(TOOL), "verify-native", str(image), "--revision", REVISION, "--native-receipt", str(proof)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["native_receipt_consistent"])
            proof.write_text(json.dumps({**receipt, "image_id": "sha256:" + "0" * 64}))
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("native_receipt_identity", result.stderr)

    def test_resolves_a_single_platform_index_wrapper_to_the_image_manifest(self):
        files = fixture()
        index = json.loads(files["index.json"])
        nested = encoded({"schemaVersion": 2, "mediaType": MEDIA + "index.v1+json", "manifests": index["manifests"]})
        digest = hashlib.sha256(nested).hexdigest()
        files["blobs/sha256/" + digest] = nested
        files["index.json"] = encoded({"schemaVersion": 2, "manifests": [{"mediaType": MEDIA + "index.v1+json", "digest": "sha256:" + digest, "size": len(nested)}]})
        result = self.invoke(archive(files))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["image_digest"], "sha256:802be08bda929fdfd2e631512683bdec849c61f39fb7cfd47297554e11bb28b8")

    def test_rejects_other_architecture_root_runtime_and_wrong_source(self):
        for files in [fixture(architecture="amd64"), fixture(user="0:0"), fixture(revision="b" * 40)]:
            with self.subTest(files=list(files)):
                self.assertNotEqual(self.invoke(archive(files)).returncode, 0)

    def test_rejects_tampered_referenced_content(self):
        files = fixture()
        manifest_name = "blobs/sha256/" + json.loads(files["index.json"])["manifests"][0]["digest"].split(":")[1]
        files[manifest_name] = files[manifest_name].replace(b"schemaVersion", b"schemaVersioX")
        result = self.invoke(archive(files))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OCI_blob_digest", result.stderr)

    def test_rejects_duplicate_JSON_fields(self):
        files = fixture()
        files["index.json"] = files["index.json"].replace(b'"schemaVersion":2', b'"schemaVersion":2,"schemaVersion":2')
        result = self.invoke(archive(files))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate_json_field", result.stderr)

    def test_bounds_archive_inventory_before_resolving_image_metadata(self):
        extra = [("blobs/sha256/" + f"{number:064x}", b"x") for number in range(129)]
        result = self.invoke(archive(fixture(), extra))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OCI_entry_limit", result.stderr)

    def test_rejects_nonzero_content_after_the_archive_terminator(self):
        result = self.invoke(archive(fixture()) + b"unlisted-trailing-payload")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OCI_trailing_content", result.stderr)
        self.assertNotIn("unlisted-trailing-payload", result.stdout + result.stderr)

    def test_rejects_external_descriptor_locations(self):
        files = fixture()
        index = json.loads(files["index.json"])
        index["manifests"][0]["urls"] = ["https://example.invalid/untrusted-image"]
        files["index.json"] = encoded(index)
        result = self.invoke(archive(files))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OCI_descriptor_fields", result.stderr)

    def test_rejects_duplicate_archive_entries_even_when_their_bytes_agree(self):
        files = fixture()
        result = self.invoke(archive(files, [("index.json", files["index.json"])]))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate_OCI_entry", result.stderr)

    def test_rejects_paths_and_payloads_outside_the_selected_image(self):
        for name in ["../escape", "/outside", "metadata/private.txt", "blobs/sha256/" + "b" * 64]:
            with self.subTest(name=name):
                files = fixture()
                files[name] = b"unexpected-payload"
                result = self.invoke(archive(files))
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("unexpected-payload", result.stdout + result.stderr)

    def test_inspects_native_OCI_identity_without_executing_or_extracting_it(self):
        result = self.invoke(archive(fixture()))
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "OCI_validated_not_release_approval")
        self.assertEqual(value["revision"], REVISION)
        self.assertEqual(value["platform"], "linux/arm64")
        self.assertEqual(value["layers"], 1)
        self.assertEqual(value["image_digest"], "sha256:802be08bda929fdfd2e631512683bdec849c61f39fb7cfd47297554e11bb28b8")


if __name__ == "__main__":
    unittest.main()
