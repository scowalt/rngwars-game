import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


sys.path.insert(0, str(Path(__file__).parents[1]))
SPEC = importlib.util.spec_from_file_location("marketing_producer", Path(__file__).parents[1] / "marketing_producer.py")
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)


class ProducerTests(unittest.TestCase):
    def context(self):
        return {"GITHUB_REPOSITORY": "scowalt/rngwars-game", "GITHUB_REPOSITORY_ID": "1442331254", "GITHUB_REF": "refs/heads/main", "GITHUB_WORKFLOW_REF": "scowalt/rngwars-game/.github/workflows/marketing-artifact.yml@refs/heads/main", "GITHUB_WORKFLOW_SHA": "a" * 40, "GITHUB_RUN_ID": "43", "GITHUB_RUN_ATTEMPT": "1", "SOURCE_CI_RUN_ID": "42"}

    def test_only_first_attempt_of_the_trusted_main_workflow_is_accepted(self):
        self.assertEqual(p.context(self.context()), (42, "a" * 40, 43))
        for key, value in [("GITHUB_REPOSITORY_ID", "1"), ("GITHUB_REF", "refs/heads/feature"), ("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_WORKFLOW_REF", "scowalt/rngwars-game/.github/workflows/other.yml@refs/heads/main"), ("SOURCE_CI_RUN_ID", "42; echo bad"), ("GITHUB_WORKFLOW_SHA", "main")]:
            with self.subTest(key=key):
                with self.assertRaises(p.m.Blocked):
                    p.context({**self.context(), key: value})

    def test_download_is_bound_to_the_exact_producer_artifact_and_transport_digest(self):
        inner = b"opaque asset archive"
        raw = p.m.encode({"assets.zip": inner})
        metadata = {"id": 44, "name": "marketing-unsealed-43-1", "expired": False, "size_in_bytes": len(raw), "digest": "sha256:" + hashlib.sha256(raw).hexdigest(), "workflow_run": {"id": 43, "repository_id": 1442331254, "head_repository_id": 1442331254, "head_sha": "a" * 40, "head_branch": "main"}}
        self.assertEqual(p.receive(metadata, raw, 44, 43, "a" * 40), inner)
        for field, value in [("id", 45), ("name", "other"), ("expired", True), ("digest", None), ("size_in_bytes", 1024 * 1024 * 1024)]:
            with self.subTest(field=field):
                with self.assertRaises(p.m.Blocked):
                    p.receive({**metadata, field: value}, raw, 44, 43, "a" * 40)
        for field, value in [("id", 99), ("repository_id", 1), ("head_repository_id", 1), ("head_sha", "b" * 40), ("head_branch", "feature")]:
            with self.subTest(field=field):
                with self.assertRaises(p.m.Blocked):
                    p.receive({**metadata, "workflow_run": {**metadata["workflow_run"], field: value}}, raw, 44, 43, "a" * 40)
        with self.assertRaises(p.m.Blocked):
            p.receive(metadata, raw + b"tampered", 44, 43, "a" * 40)

    def test_outer_archive_rejects_links_extra_files_and_wrong_names(self):
        for names, mode in [(["../assets.zip"], stat.S_IFREG), (["assets.zip", "extra"], stat.S_IFREG), (["assets.zip"], stat.S_IFLNK)]:
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, "w") as archive:
                for name in names:
                    item = zipfile.ZipInfo(name)
                    item.external_attr = (mode | 0o644) << 16
                    archive.writestr(item, b"opaque")
            with self.assertRaises(p.m.Blocked):
                p.single_file(raw.getvalue(), "assets.zip")

    def test_signature_verification_constrains_workflow_revision_ref_and_run(self):
        raw = b"synthetic signed artifact bytes"
        digest = hashlib.sha256(raw).hexdigest()
        statement = {"subject": [{"digest": {"sha256": digest}}], "predicateType": "https://slsa.dev/provenance/v1", "predicate": {"runDetails": {"metadata": {"invocationId": "https://github.com/scowalt/rngwars-game/actions/runs/43/attempts/1"}}}}
        calls = []

        def verifier(command, **options):
            self.assertEqual(Path(command[3]).read_bytes(), raw)
            self.assertEqual(command[command.index("--signer-digest") + 1], "a" * 40)
            self.assertEqual(command[command.index("--source-ref") + 1], "refs/heads/main")
            self.assertEqual(command[command.index("--cert-identity") + 1], "https://github.com/" + p.WORKFLOW)
            self.assertIn("--deny-self-hosted-runners", command)
            self.assertNotIn("CLOUDFLARE_API_TOKEN", options["env"])
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, json.dumps([{"verificationResult": {"statement": statement}}]).encode(), b"")

        with patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "synthetic-provider-capability"}):
            self.assertEqual(p.verify_signature(raw, "a" * 40, 43, runner=verifier), digest)
        self.assertEqual(len(calls), 1)
        statement["predicate"]["runDetails"]["metadata"]["invocationId"] = "https://github.com/scowalt/rngwars-game/actions/runs/44/attempts/1"
        with self.assertRaises(p.m.Blocked):
            p.verify_signature(raw, "a" * 40, 43, runner=verifier)
        with self.assertRaises(p.m.Blocked):
            p.verify_signature(raw, "a" * 40, 43, runner=lambda command, **options: subprocess.CompletedProcess(command, 1, b"", b"verification failed"))

    def test_bundle_digest_output_accepts_its_actual_numeric_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "step-output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(path)}):
                p.output({"source_revision": "a" * 40})
                p.output({"bundle_sha256": "b" * 64})
            self.assertEqual(path.read_text(), "source_revision=" + "a" * 40 + "\nbundle_sha256=" + "b" * 64 + "\n")

    def test_step_output_still_rejects_missing_channel_or_injected_lines(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(p.m.Blocked):
                p.output({"bundle_sha256": "b" * 64})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "step-output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(path)}):
                for value in [{"bundle_sha256": "safe\ninjected=value"}, {"key\ninjected": "value"}, {"key": "value=value"}]:
                    with self.assertRaises(p.m.Blocked):
                        p.output(value)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
