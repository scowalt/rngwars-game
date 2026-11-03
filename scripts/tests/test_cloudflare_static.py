import importlib.util
import json
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).parents[1]))
SPEC = importlib.util.spec_from_file_location("cloudflare_static", Path(__file__).parents[1] / "cloudflare_static.py")
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)


class Fake:
    worker = "fixture-worker"

    def __init__(self):
        self.secrets = []
        self.calls = []

    def request(self, method, path, data=None, content_type=None, token=None):
        self.calls.append((method, path, data, content_type, token))
        if path.endswith("assets-upload-session"):
            return {"jwt": "x" * 32, "buckets": [[x["hash"] for x in data["manifest"].values()]]}
        if path.endswith("assets/upload?base64=true"):
            return {"jwt": "y" * 32}
        if path.endswith("/versions"):
            return {"id": "11111111-1111-1111-1111-111111111111"}
        if path.endswith("/deployments"):
            return {"id": "synthetic"}
        raise AssertionError(path)


BINDING = {"worker_tag": "a" * 32, "compatibility_date": "2024-12-01", "compatibility_flags": [], "native_trigger_ids": ["production", "preview"]}


class ControllerState(Fake):
    def __init__(self):
        super().__init__()
        self.triggers = []
        self.status = "stopped"
        self.repeat_page = False

    def request(self, method, path, data=None, content_type=None, token=None):
        self.calls.append((method, path))
        if "/services/" in path:
            return {"default_environment": {"script": {"id": self.worker, "tag": "a" * 32}}}
        if path.endswith("/settings"):
            return {"bindings": [], "compatibility_date": "2024-12-01", "compatibility_flags": []}
        if path.endswith("/triggers"):
            return {"triggers": self.triggers}
        return [{"build_uuid": "build", "status": self.status}] if "page=1" in path or self.repeat_page else []


class StaticReleaseTests(unittest.TestCase):
    def test_uploads_only_static_assets_and_keeps_header_rules_as_metadata(self):
        client = Fake()
        version = c.upload(client, {"compatibility_date": "2024-12-01", "compatibility_flags": []}, {"index.html": b"site", "_headers": b"/*\n  X-Test: fixture\n"}, 42, "a" * 40, "b" * 64)
        self.assertEqual(version, "11111111-1111-1111-1111-111111111111")
        self.assertEqual(set(client.calls[0][2]["manifest"]), {"/index.html"})
        self.assertEqual([x[1] for x in client.calls], ["/workers/scripts/fixture-worker/assets-upload-session", "/workers/assets/upload?base64=true", "/workers/scripts/fixture-worker/versions"])
        metadata_bytes = client.calls[-1][2]
        self.assertIn(b'"_headers": "/*\\n  X-Test: fixture\\n"', metadata_bytes)
        self.assertNotIn(b"main_module", metadata_bytes)
        self.assertNotIn(b"routes", metadata_bytes)
        self.assertEqual(client.calls[1][4], "x" * 32)
        self.assertEqual(client.secrets, ["x" * 32, "y" * 32])

    def test_production_promotion_is_a_separate_exact_version_operation(self):
        client = Fake()
        c.promote(client, "11111111-1111-1111-1111-111111111111")
        self.assertEqual(client.calls[0][2], {"strategy": "percentage", "versions": [{"version_id": "11111111-1111-1111-1111-111111111111", "percentage": 100}]})
        with self.assertRaises(c.Blocked):
            c.promote(client, "latest")

    def test_server_cannot_request_unknown_asset_bytes(self):
        class Unknown(Fake):
            def request(self, method, path, data=None, content_type=None, token=None):
                if path.endswith("assets-upload-session"):
                    return {"jwt": "x" * 32, "buckets": [["f" * 32]]}
                return super().request(method, path, data, content_type, token)
        client = Unknown()
        with self.assertRaises(c.Blocked):
            c.upload(client, {"compatibility_date": "2024-12-01", "compatibility_flags": []}, {"index.html": b"site"}, 42, "a" * 40, "b" * 64)
        self.assertEqual(client.calls, [])

    def test_branch_and_path_filters_are_not_a_controller_fence(self):
        for filters in [{"branch_excludes": ["*"]}, {"branch_includes": ["main"], "branch_excludes": []}, {"path_excludes": ["*"]}]:
            with self.subTest(filters=filters):
                client = ControllerState()
                client.triggers = [{"trigger_uuid": x, "external_script_id": "a" * 32, **filters} for x in ["production", "preview"]]
                with self.assertRaises(c.Blocked):
                    c.fenced(client, BINDING)

    def test_disconnected_controllers_still_require_complete_idle_build_inventory(self):
        client = ControllerState()
        c.fenced(client, BINDING)
        self.assertTrue(any("page=2" in path for method, path in client.calls))
        self.assertTrue(all(method == "GET" for method, path in client.calls))
        for status in ["queued", "running"]:
            with self.subTest(status=status):
                client = ControllerState()
                client.status = status
                with self.assertRaises(c.Blocked):
                    c.fenced(client, BINDING)

    def test_new_or_malformed_controller_inventory_cannot_pass(self):
        for inventory in [[{"trigger_uuid": "unexpected"}], None, {}]:
            with self.subTest(inventory=inventory):
                client = ControllerState()
                client.triggers = inventory
                with self.assertRaises(c.Blocked):
                    c.fenced(client, BINDING)

    def test_disconnection_does_not_excuse_repeating_build_pages(self):
        client = ControllerState()
        client.repeat_page = True
        with self.assertRaises(c.Blocked):
            c.fenced(client, BINDING)


if __name__ == "__main__":
    unittest.main()
