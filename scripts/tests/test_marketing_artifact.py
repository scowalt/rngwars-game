import copy
import hashlib
import importlib.util
import io
import stat
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile


SPEC = importlib.util.spec_from_file_location("marketing_artifact", Path(__file__).parents[1] / "marketing_artifact.py")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class MarketingArtifactTests(unittest.TestCase):
    def test_pack_preserves_static_asset_bytes_without_executing_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "dist"
            source.mkdir()
            (source / "index.html").write_bytes(b"<h1>RNGWars</h1>")
            (source / "_headers").write_bytes(b"/*\n  X-Frame-Options: DENY\n")
            m.pack(source, root / "assets.zip")
            with zipfile.ZipFile(root / "assets.zip") as archive:
                self.assertEqual(archive.read("index.html"), b"<h1>RNGWars</h1>")
                self.assertEqual(archive.read("_headers"), b"/*\n  X-Frame-Options: DENY\n")

    def test_pack_rejects_a_link_to_content_outside_the_site(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "dist"
            source.mkdir()
            (root / "private.txt").write_bytes(b"synthetic private content")
            (source / "index.html").symlink_to(root / "private.txt")
            with self.assertRaises(m.Blocked):
                m.pack(source, root / "assets.zip")
            self.assertFalse((root / "assets.zip").exists())

    def test_untrusted_archive_is_read_without_extracting_paths_or_links(self):
        for name, mode in [("../index.html", 0o100644), ("/index.html", 0o100644), ("a\\index.html", 0o100644), ("index.html", stat.S_IFLNK | 0o777)]:
            with self.subTest(name=name, mode=mode):
                raw = io.BytesIO()
                with zipfile.ZipFile(raw, "w") as archive:
                    item = zipfile.ZipInfo(name)
                    item.external_attr = mode << 16
                    archive.writestr(item, b"synthetic")
                with self.assertRaises(m.Blocked):
                    m.assets(raw.getvalue())

    def test_pack_is_deterministic_and_does_not_replace_an_existing_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "dist"
            source.mkdir()
            (source / "index.html").write_bytes(b"<h1>RNGWars</h1>")
            m.pack(source, root / "first.zip")
            (source / "index.html").chmod(0o755)
            m.pack(source, root / "second.zip")
            self.assertEqual((root / "first.zip").read_bytes(), (root / "second.zip").read_bytes())
            with self.assertRaises(FileExistsError):
                m.pack(source, root / "first.zip")

    def test_bundle_manifest_binds_exact_source_and_asset_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            site = root / "dist"
            site.mkdir()
            (site / "index.html").write_bytes(b"<h1>RNGWars</h1>")
            m.pack(site, root / "assets.zip")
            identity = {"repository": "scowalt/rngwars-game", "repository_id": 1442331254, "source_revision": "a" * 40, "source_branch": "feature/site", "ci_run_id": 42, "workflow_revision": "b" * 40, "producer_run_id": 43}
            digest = m.bundle((root / "assets.zip").read_bytes(), identity, root / "release.zip")
            self.assertEqual(digest, hashlib.sha256((root / "release.zip").read_bytes()).hexdigest())
            manifest, files = m.inspect_bundle((root / "release.zip").read_bytes())
            self.assertEqual(manifest["identity"], identity)
            self.assertEqual(files, {"index.html": b"<h1>RNGWars</h1>"})
            self.assertEqual(manifest["files"]["index.html"]["size"], 16)
            with zipfile.ZipFile(root / "release.zip") as source:
                raw = io.BytesIO()
                with zipfile.ZipFile(raw, "w") as changed:
                    changed.writestr("manifest.json", source.read("manifest.json"))
                    changed.writestr("assets/index.html", b"tampered")
            with self.assertRaises(m.Blocked):
                m.inspect_bundle(raw.getvalue())

    def test_source_identity_is_derived_from_successful_exact_commit_ci(self):
        data = {
            "": {"id": 1442331254, "private": False, "default_branch": "main"},
            "/git/ref/heads/main": {"object": {"sha": "b" * 40}},
            "/git/ref/heads/feature/site": {"object": {"sha": "a" * 40}},
            "/actions/workflows/ci.yml": {"id": 100, "path": ".github/workflows/ci.yml", "state": "active"},
            "/actions/runs/42": {"id": 42, "repository": {"id": 1442331254}, "head_repository": {"id": 1442331254}, "head_sha": "a" * 40, "head_branch": "feature/site", "event": "push", "run_attempt": 1, "status": "completed", "conclusion": "success", "workflow_id": 100, "path": ".github/workflows/ci.yml"},
            "/actions/runs/42/attempts/1/jobs?per_page=100": {"total_count": 3, "jobs": [{"name": name, "status": "completed", "conclusion": "success"} for name in ["Build API (F#)", "Build Frontend (SolidJS)", "Portable SQLite backup and deployment preparation"]]},
            "/contents/.github/workflows/ci.yml?ref=" + "a" * 40: {"type": "file", "sha": "c" * 40},
            "/contents/.github/workflows/ci.yml?ref=" + "b" * 40: {"type": "file", "sha": "c" * 40},
        }
        result = m.resolve_ci(42, "b" * 40, api=lambda path: copy.deepcopy(data[path]))
        self.assertEqual(result["source_revision"], "a" * 40)
        self.assertEqual(result["source_branch"], "feature/site")
        for field, value in [("event", "pull_request"), ("conclusion", "failure"), ("run_attempt", 2), ("head_repository", {"id": 1}), ("workflow_id", 101), ("head_sha", "d" * 40)]:
            with self.subTest(field=field):
                changed = copy.deepcopy(data)
                changed["/actions/runs/42"][field] = value
                with self.assertRaises(m.Blocked):
                    m.resolve_ci(42, "b" * 40, api=lambda path: copy.deepcopy(changed[path]))
        changed = copy.deepcopy(data)
        changed["/contents/.github/workflows/ci.yml?ref=" + "a" * 40]["sha"] = "d" * 40
        with self.assertRaises(m.Blocked):
            m.resolve_ci(42, "b" * 40, api=lambda path: copy.deepcopy(changed[path]))

    def test_missing_index_hidden_paths_and_duplicate_names_are_rejected(self):
        for entries in [[("other.html", b"x")], [("index.html", b"")], [(".env", b"synthetic"), ("index.html", b"x")], [("index.html", b"one"), ("index.html", b"two")], [("dir//index.html", b"x")], [("C:/index.html", b"x")]]:
            with self.subTest(names=[name for name, _ in entries]):
                raw = io.BytesIO()
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    with zipfile.ZipFile(raw, "w") as archive:
                        for name, content in entries:
                            archive.writestr(name, content)
                with self.assertRaises(m.Blocked):
                    m.assets(raw.getvalue())

    def test_oversized_compressed_file_is_rejected_before_materialization(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("index.html", b"x" * (26 * 1024 * 1024))
        with self.assertRaises(m.Blocked):
            m.assets(raw.getvalue())

    def test_missing_index_does_not_leave_a_partial_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "dist"
            source.mkdir()
            with self.assertRaises(m.Blocked):
                m.pack(source, root / "assets.zip")
            self.assertFalse((root / "assets.zip").exists())

    def test_extra_manifest_fields_are_not_an_operational_configuration_channel(self):
        identity = {"repository": "scowalt/rngwars-game", "repository_id": 1442331254, "source_revision": "a" * 40, "source_branch": "main", "ci_run_id": 42, "workflow_revision": "b" * 40, "producer_run_id": 43, "deployment_target": "unreviewed"}
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(m.Blocked):
                m.bundle(b"anything", identity, Path(temporary) / "release.zip")

    def test_duplicate_json_keys_are_rejected(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w") as archive:
            archive.writestr("manifest.json", b'{"version":1,"version":1}')
            archive.writestr("assets/index.html", b"x")
        with self.assertRaises(m.Blocked):
            m.inspect_bundle(raw.getvalue())

    def test_malformed_archives_are_rejected(self):
        for raw in [b"", b"not a zip", b"PK\\x03\\x04"]:
            with self.subTest(raw=raw):
                with self.assertRaises(m.Blocked):
                    m.assets(raw)


if __name__ == "__main__":
    unittest.main()
