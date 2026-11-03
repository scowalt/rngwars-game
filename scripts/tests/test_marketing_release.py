import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).parents[1]))
SPEC = importlib.util.spec_from_file_location("marketing_release", Path(__file__).parents[1] / "marketing_release.py")
r = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r)


class ReleaseTests(unittest.TestCase):
    def test_only_reviewed_main_first_attempt_can_use_the_release_interface(self):
        env = {"GITHUB_REPOSITORY_ID": "1442331254", "GITHUB_REPOSITORY": "scowalt/rngwars-game", "GITHUB_REF": "refs/heads/main", "GITHUB_WORKFLOW_REF": r.WORKFLOW, "GITHUB_RUN_ATTEMPT": "1", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_WORKFLOW_SHA": "a" * 40, "GITHUB_RUN_ID": "42"}
        self.assertEqual(r.context(env), ("a" * 40, 42))
        for key, value in [("GITHUB_REF", "refs/tags/main"), ("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_REPOSITORY_ID", "1"), ("GITHUB_EVENT_NAME", "pull_request_target")]:
            with self.subTest(key=key):
                with self.assertRaises(r.m.Blocked):
                    r.context({**env, key: value})

    def test_an_unfenced_controller_blocks_all_reservations_and_provider_writes(self):
        info = {"kind": "production", "bundle_sha256": "a" * 64}
        binding = {"account_id": "a" * 32, "worker_name": "fixture-worker"}
        env = {"MARKETING_RELEASE_ENABLED": "true", "RELEASE_KIND": "production", **{name: "synthetic" for name in ["CLOUDFLARE_API_TOKEN", "RELEASE_STORAGE_ACCESS_KEY_ID", "RELEASE_STORAGE_SECRET_ACCESS_KEY", "RELEASE_LOG_ENCRYPTION_KEY", "GH_TOKEN"]}}
        with patch.dict(os.environ, env), patch.object(r.cf, "fenced", side_effect=r.m.Blocked("native_controller_not_fenced")), patch.object(r, "reserve") as reserve, patch.object(r.cf, "upload") as upload, patch.object(r, "evidence"):
            with self.assertRaises(r.m.Blocked):
                r.deploy(info, {"index.html": b"RNGWars"}, "b" * 40, 42, binding)
            reserve.assert_not_called()
            upload.assert_not_called()

    def test_preview_preserves_disabled_preview_URLs_and_never_promotes(self):
        info = {"kind": "preview", "bundle_sha256": "a" * 64, "source_revision": "b" * 40}
        binding = {"account_id": "a" * 32, "worker_name": "fixture-worker", "health_origin": "https://example.invalid"}
        env = {"MARKETING_RELEASE_ENABLED": "true", "RELEASE_KIND": "preview", **{name: "synthetic" for name in ["CLOUDFLARE_API_TOKEN", "RELEASE_STORAGE_ACCESS_KEY_ID", "RELEASE_STORAGE_SECRET_ACCESS_KEY", "RELEASE_LOG_ENCRYPTION_KEY", "GH_TOKEN"]}}
        version = "11111111-1111-1111-1111-111111111111"
        class Client:
            worker = "fixture-worker"
            secrets = []
            events = []
            def request(self, method, path):
                self.assert_read(method)
                if path.endswith("/subdomain"):
                    return {"previews_enabled": False}
                return {"id": version}
            def assert_read(self, method):
                if method != "GET":
                    raise AssertionError(method)
        with patch.dict(os.environ, env), patch.object(r.cf, "Client", return_value=Client()), patch.object(r.cf, "fenced"), patch.object(r.cf, "active_version", return_value="baseline"), patch.object(r.cf, "upload", return_value=version), patch.object(r.cf, "promote") as promote, patch.object(r, "reserve"), patch.object(r, "evidence") as evidence, patch.object(r, "health", return_value={"passed": True}):
            with patch("builtins.print"):
                r.deploy(info, {"index.html": b"RNGWars"}, "c" * 40, 42, binding)
            promote.assert_not_called()
            self.assertTrue(evidence.call_args.args[4]["health"]["preview_urls_preserved_disabled"])

    def test_lost_promotion_reply_is_resolved_by_readback_without_repeating_the_write(self):
        info = {"kind": "production", "bundle_sha256": "a" * 64, "source_revision": "b" * 40}
        binding = {"account_id": "a" * 32, "worker_name": "fixture-worker", "health_origin": "https://example.invalid"}
        env = {"MARKETING_RELEASE_ENABLED": "true", "RELEASE_KIND": "production", **{name: "synthetic" for name in ["CLOUDFLARE_API_TOKEN", "RELEASE_STORAGE_ACCESS_KEY_ID", "RELEASE_STORAGE_SECRET_ACCESS_KEY", "RELEASE_LOG_ENCRYPTION_KEY", "GH_TOKEN"]}}
        state = {"active": "baseline"}
        def promotion(client, version):
            state["active"] = version
            raise TimeoutError()
        with patch.dict(os.environ, env), patch.object(r.cf, "fenced"), patch.object(r.cf, "active_version", side_effect=lambda client: state["active"]), patch.object(r.cf, "upload", return_value="new"), patch.object(r.cf, "promote", side_effect=promotion) as promote, patch.object(r, "reserve"), patch.object(r, "evidence"), patch.object(r, "health", return_value={"passed": True}):
            with patch("builtins.print"):
                r.deploy(info, {"index.html": b"RNGWars"}, "c" * 40, 42, binding)
            self.assertEqual(promote.call_count, 1)
            self.assertEqual(state["active"], "new")

    def test_known_failed_production_health_rolls_back_once_to_captured_version(self):
        info = {"kind": "production", "bundle_sha256": "a" * 64, "source_revision": "b" * 40}
        binding = {"account_id": "a" * 32, "worker_name": "fixture-worker", "health_origin": "https://example.invalid"}
        env = {"MARKETING_RELEASE_ENABLED": "true", "RELEASE_KIND": "production", **{name: "synthetic" for name in ["CLOUDFLARE_API_TOKEN", "RELEASE_STORAGE_ACCESS_KEY_ID", "RELEASE_STORAGE_SECRET_ACCESS_KEY", "RELEASE_LOG_ENCRYPTION_KEY", "GH_TOKEN"]}}
        state = {"active": "baseline"}
        def promotion(client, version):
            state["active"] = version
        with patch.dict(os.environ, env), patch.object(r.cf, "fenced"), patch.object(r.cf, "active_version", side_effect=lambda client: state["active"]), patch.object(r.cf, "upload", return_value="new"), patch.object(r.cf, "promote", side_effect=promotion) as promote, patch.object(r, "reserve"), patch.object(r, "evidence"), patch.object(r.time, "sleep"), patch.object(r, "health", side_effect=[{"passed": True}] + [{"passed": False}] * 5 + [{"passed": True}]):
            with self.assertRaises(r.m.Blocked):
                r.deploy(info, {"index.html": b"RNGWars"}, "c" * 40, 42, binding)
            self.assertEqual([call.args[1] for call in promote.call_args_list], ["new", "baseline"])
            self.assertEqual(state["active"], "baseline")


if __name__ == "__main__":
    unittest.main()
