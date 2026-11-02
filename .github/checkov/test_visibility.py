import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(".github/checkov/private-repository.tfvars")
PRIVACY_FINDING = ("CKV_GIT_1", "github_repository.rngwars")


class RepositoryVisibilityScanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="checkov-visibility-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.workspace = self.directory / "workspace"
        self.workspace.mkdir()
        home = self.directory / "home"
        home.mkdir()
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "ANSI_COLORS_DISABLED": "true",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
        }
        sibling = Path(sys.executable).parent / "checkov"
        self.checkov = str(sibling) if sibling.is_file() else shutil.which("checkov")
        self.assertIsNotNone(self.checkov, "Install Checkov before running these tests")
        workflow = yaml.load(
            (ROOT / ".github/workflows/terraform.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        self.workflow = workflow
        steps = workflow["jobs"]["opentofu-check"]["steps"]
        scanners = [
            step
            for step in steps
            if step.get("uses", "").startswith("bridgecrewio/checkov-action@")
        ]
        self.assertEqual(len(scanners), 1)
        self.scanner = scanners[0]
        self.scan = self.scanner["with"]
        tracked = subprocess.run(
            ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT), "ls-files", "-z", "--", "infra"],
            env=self.env,
            capture_output=True,
            check=True,
        ).stdout
        self.source_hashes = {}
        for raw in tracked.split(b"\0"):
            if not raw:
                continue
            relative = Path(os.fsdecode(raw))
            source = ROOT / relative
            self.assertFalse(source.is_symlink())
            self.assertTrue(source.is_file() and source.resolve().is_relative_to(ROOT))
            data = source.read_bytes()
            self.source_hashes[relative] = hashlib.sha256(data).hexdigest()
            target = self.workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.assertIn(Path("infra/github.tf"), self.source_hashes)
        self.addCleanup(self.assert_source_unchanged)
        fixture = self.workspace / FIXTURE
        fixture.parent.mkdir(parents=True)
        fixture.write_bytes((ROOT / FIXTURE).read_bytes())
        self.config = self.directory / "empty-checkov.yaml"
        self.config.write_text("{}\n")

    def assert_source_unchanged(self):
        for path, digest in self.source_hashes.items():
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest)

    def run_scan(self, *, binding=None, omit_binding=False, literal_public=False):
        self.assertEqual(PurePosixPath(self.scan["directory"]), PurePosixPath("infra"))
        self.assertEqual(self.scan["framework"], "terraform")
        command = [
            self.checkov,
            "--directory", self.scan["directory"],
            "--framework", self.scan["framework"],
            "--skip-check", self.scan["skip_check"],
            "--config-file", str(self.config),
            "--skip-download",
            "--quiet",
            "--output", "json",
        ]
        if binding is not None:
            (self.workspace / FIXTURE).write_text(
                f"repository_visibility = {json.dumps(binding)}\n"
            )
        if not omit_binding and self.scan.get("var_file"):
            self.assertEqual(self.scan["var_file"], FIXTURE.as_posix())
            command.extend(["--var-file", self.scan["var_file"]])
        if literal_public:
            source = self.workspace / "infra/github.tf"
            original = source.read_text()
            self.assertEqual(original.count("var.repository_visibility"), 1)
            changed = original.replace("var.repository_visibility", '"public"')
            source.write_text(changed)
            self.assertNotEqual(source.read_bytes(), (ROOT / "infra/github.tf").read_bytes())
        completed = subprocess.run(
            command,
            cwd=self.workspace,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertIn(completed.returncode, (0, 1), "Scanner execution failed")
        self.assertLess(len(completed.stdout), 5_000_000)
        report = json.loads(completed.stdout)
        self.assertEqual(report["check_type"], "terraform")
        self.assertEqual(report["summary"]["parsing_errors"], 0)
        failures = {
            (finding["check_id"], finding["resource"])
            for finding in report["results"].get("failed_checks", [])
        }
        return completed.returncode, report["summary"], failures

    def test_configured_scan_accepts_synthetic_private_configuration(self):
        status, summary, failures = self.run_scan()
        self.assertEqual(status, 0, (summary, sorted(failures)))
        self.assertEqual(summary["failed"], 0)
        self.assertGreater(summary["passed"], 0)
        self.assertEqual(summary["skipped"], 0)

    def assert_privacy_rejected(self, **case):
        status, summary, failures = self.run_scan(**case)
        self.assertEqual(status, 1, summary)
        self.assertEqual(failures, {PRIVACY_FINDING})
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["skipped"], 0)

    def test_public_binding_is_rejected(self):
        self.assert_privacy_rejected(binding="public")

    def test_unbound_visibility_is_rejected(self):
        self.assert_privacy_rejected(omit_binding=True)

    def test_private_fixture_cannot_mask_literal_public_resource(self):
        self.assert_privacy_rejected(literal_public=True)

    def test_workflow_keeps_privacy_check_and_fixture_coverage(self):
        self.assertEqual(
            {check.strip() for check in self.scan["skip_check"].split(",")},
            {"CKV_TF_1", "CKV_GIT_5", "CKV_GIT_6"},
        )
        for control in (
            "soft_fail", "soft_fail_on", "hard_fail_on", "check", "config_file",
            "baseline", "skip_framework", "skip_path",
        ):
            self.assertNotIn(control, self.scan)
        self.assertNotIn("if", self.scanner)
        self.assertEqual(self.scanner.get("continue-on-error", "false"), "false")
        self.assertEqual(
            self.workflow["jobs"]["opentofu-check"].get("continue-on-error", "false"),
            "false",
        )
        self.assertEqual(self.scan["var_file"], FIXTURE.as_posix())
        self.assertIn(".github/checkov/**", self.workflow["on"]["pull_request"]["paths"])
        for directory in (ROOT, ROOT / "infra"):
            for name in (".checkov.yml", ".checkov.yaml"):
                self.assertFalse((directory / name).exists(), "Review new scanner configuration explicitly")


if __name__ == "__main__":
    unittest.main()
