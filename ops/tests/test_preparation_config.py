import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class PreparationTests(unittest.TestCase):
    def test_backup_module_uses_explicit_identity_and_keeps_bucket_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "game-backups"
            shutil.copytree(ROOT / "infra/game-backups", target)
            environment = {
                "PATH": os.environ["PATH"], "HOME": directory,
                "TF_REGISTRY_DISCOVERY_RETRY": "3",
                "TF_REGISTRY_CLIENT_TIMEOUT": "30",
                "TF_PROVIDER_DOWNLOAD_RETRY": "3",
                "TF_VAR_account_id": "a" * 32,
                "TF_VAR_bucket_item_write_permission_group_id": "b" * 32,
                "TF_VAR_bucket_name": "fixture-backup-bucket",
                "TF_VAR_repository_prefix": "fixture-prefix",
                "TF_VAR_bucket_location": "WEUR",
                "TF_VAR_credential_request_name": "fixture-scope",
            }
            for arguments in [["init", "-backend=false", "-input=false"], ["validate"]]:
                result = subprocess.run(["tofu", *arguments], cwd=target, env=environment, capture_output=True, text=True, timeout=180)
                diagnostic = re.sub(r"(https?://[^\s?#\"']+)[?#][^\s\"']+", r"\1?<redacted>", result.stdout + result.stderr)
                self.assertEqual(result.returncode, 0, "tofu " + arguments[0] + " failed:\n" + diagnostic[-8192:])
            expression = "jsonencode([local.repository, local.credential_request])"
            result = subprocess.run(["tofu", "console"], cwd=target, env=environment, input=expression, text=True, check=True, capture_output=True)
            repository, request = json.loads(json.loads(result.stdout))
            self.assertEqual(repository, "s3:https://" + "a" * 32 + ".r2.cloudflarestorage.com/fixture-backup-bucket/fixture-prefix")
            self.assertEqual(request["policies"][0]["resources"], {"com.cloudflare.edge.r2.bucket." + "a" * 32 + "_default_fixture-backup-bucket": "*"})
            self.assertEqual(request["policies"][0]["permission_groups"], [{"id": "b" * 32, "name": "Workers R2 Storage Bucket Item Write"}])
            self.assertIn("prevent_destroy = true", (target / "main.tf").read_text())

    def test_synthetic_provider_failure_reports_bounded_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = Path(directory) / "tofu"
            tool.write_text("#!" + sys.executable + "\nimport os,sys\nassert os.environ['TF_REGISTRY_DISCOVERY_RETRY']=='3'\nassert os.environ['TF_REGISTRY_CLIENT_TIMEOUT']=='30'\nassert os.environ['TF_PROVIDER_DOWNLOAD_RETRY']=='3'\nprint('x'*16000)\nprint('fixture-provider-unavailable https://provider.invalid/archive?token=synthetic-provider-query-value',file=sys.stderr)\nraise SystemExit(17)\n")
            tool.chmod(0o700)
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "PreparationTests.test_backup_module_uses_explicit_identity_and_keeps_bucket_scope"], env={**os.environ, "PATH": directory + os.pathsep + os.environ["PATH"]}, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("fixture-provider-unavailable", result.stderr)
            self.assertNotIn("synthetic-provider-query-value", result.stderr)
            self.assertLess(len(result.stderr), 11000)

    def test_CI_tool_fetches_have_bounded_transient_retries_and_still_require_checksums(self):
        ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        steps = ci["jobs"]["portable-sqlite-ops"]["steps"]
        script = next(step["run"] for step in steps if step.get("name") == "Install tested Restic from official checksums")
        downloads = [line for line in script.splitlines() if line.strip().startswith("curl ")]
        self.assertEqual(len(downloads), 2)
        for line in downloads:
            for option in ["--retry 3", "--retry-max-time 120", "--connect-timeout 10", "--max-time 60", "--proto '=https'", "--proto-redir '=https'"]:
                self.assertIn(option, line)
            self.assertNotIn("--retry-all-errors", line)
            self.assertNotIn("--insecure", line)
        self.assertIn("sha256sum --check --strict", script)
        self.assertLess(script.index("sha256sum --check --strict"), script.index("chmod 0555"))

    def test_repository_and_host_identity_have_no_implicit_live_defaults(self):
        provider = (ROOT / "infra/providers.tf").read_text()
        self.assertIn('backend "s3" {}', provider)
        self.assertNotIn("cloudflarestorage.com", provider)
        github = (ROOT / "infra/github.tf").read_text()
        self.assertRegex(github, r"visibility\s*=\s*var\.repository_visibility")
        self.assertNotIn('visibility  = "public"', github)
        self.assertNotIn('visibility  = "private"', github)
        for name in ["Build API (F#)", "Build Frontend (SolidJS)"]:
            self.assertEqual(github.count(name), 3)
        import re
        for setting in ["allows_force_pushes", "allows_deletions"]:
            self.assertEqual(len(re.findall(setting + r"\s*=\s*false", github)), 3)
        host = (ROOT / "infra/hetzner.tf").read_text()
        self.assertIn("prevent_destroy = true", host)
        self.assertIn("ignore_changes  = [user_data]", host)
        self.assertIn("for_each = var.firewall_rules", host)
        self.assertNotIn('port       = "22"', host)

    def test_main_merge_protection_keeps_admin_enforcement_and_all_three_CI_gates(self):
        source = (ROOT / "infra/github.tf").read_text()
        main = source.split('resource "github_branch_protection" "main" {', 1)[1].split('resource "github_branch_protection" "release" {', 1)[0]
        self.assertRegex(main, r"enforce_admins\s*=\s*true")
        self.assertIn('"Portable SQLite backup and deployment preparation"', main)
        self.assertIn("required_pull_request_reviews", main)
        self.assertRegex(main, r"allows_force_pushes\s*=\s*false")
        self.assertRegex(main, r"allows_deletions\s*=\s*false")

    def test_ci_covers_promotions_and_has_no_secret_or_publisher_jobs(self):
        ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        self.assertEqual(ci[True]["push"]["branches"], ["**"])
        self.assertEqual(ci[True]["pull_request"]["branches"], ["main", "release", "production"])
        for event in ["push", "pull_request"]:
            self.assertNotIn("paths", ci[True][event])
        self.assertEqual(ci["permissions"], {"contents": "read"})
        self.assertIn("portable-sqlite-ops", ci["jobs"])
        self.assertNotIn("secrets.", json.dumps(ci))
        self.assertFalse((ROOT / ".github/workflows/deploy-production.yml").exists())


if __name__ == "__main__":
    unittest.main()
