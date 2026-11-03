import base64
import hashlib
import json
import mimetypes
import re
import secrets
import urllib.error
import urllib.request

from marketing_artifact import Blocked, require


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Client:
    def __init__(self, account, worker, token):
        require(re.fullmatch(r"[a-f0-9]{32}", account) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", worker), "provider_binding")
        self.prefix = "/accounts/" + account
        self.worker = worker
        self.token = token
        self.secrets = [token]
        self.events = []

    def request(self, method, path, data=None, content_type="application/json", token=None):
        require(method in {"GET", "POST"} and path.startswith("/") and ".." not in path and "\r" not in path and "\n" not in path, "provider_route")
        require(path.startswith(("/workers/", "/builds/workers/")), "provider_route")
        raw = json.dumps(data).encode() if isinstance(data, dict) else data
        headers = {"Authorization": "Bearer " + (token or self.token), "Accept": "application/json"}
        if raw is not None:
            headers["Content-Type"] = content_type
        request = urllib.request.Request("https://api.cloudflare.com/client/v4" + self.prefix + path, data=raw, headers=headers, method=method)
        event = {"method": method, "path": path}
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=60) as response:
                event["status"] = response.status
                body = response.read(8 * 1024 * 1024 + 1)
                require(len(body) <= 8 * 1024 * 1024, "provider_response_size")
                result = json.loads(body)
                require(result.get("success") is True, "provider_result_failed")
                self.last_info = result.get("result_info")
                return result["result"]
        except urllib.error.HTTPError as error:
            event["status"] = error.code
            try:
                value = json.loads(error.read(65536))
                event["error_codes"] = [x["code"] for x in value.get("errors", []) if isinstance(x, dict) and type(x.get("code")) is int]
            except Exception:
                pass
            error.close()
            raise Blocked("provider_http_" + str(event["status"])) from None
        finally:
            self.events.append(event)


def multipart(parts):
    boundary = "rngwars-" + secrets.token_hex(16)
    encoded = []
    for name, kind, content in parts:
        require(re.fullmatch(r"[a-zA-Z0-9._-]+", name) and "\r" not in kind and "\n" not in kind, "multipart_name")
        encoded.extend([("--" + boundary + "\r\n").encode(), (f'Content-Disposition: form-data; name="{name}"; filename="{name}"\r\nContent-Type: {kind}\r\n\r\n').encode(), content, b"\r\n"])
    encoded.append(("--" + boundary + "--\r\n").encode())
    return b"".join(encoded), "multipart/form-data; boundary=" + boundary


def active_version(client):
    value = client.request("GET", f"/workers/scripts/{client.worker}/deployments")
    items = value["deployments"] if isinstance(value, dict) else value
    require(isinstance(items, list) and bool(items), "no_active_deployment")
    versions = items[0]["versions"]
    require(len(versions) == 1 and versions[0]["percentage"] == 100, "split_traffic_unreviewed")
    version = versions[0]["version_id"]
    require(re.fullmatch(r"[a-f0-9-]{36}", version), "version_identity")
    return version


def inspect_worker(client, binding):
    service = client.request("GET", f"/workers/services/{client.worker}")
    script = service["default_environment"]["script"]
    require(script["id"] == client.worker and script["tag"] == binding["worker_tag"], "worker_identity_drift")
    settings = client.request("GET", f"/workers/scripts/{client.worker}/settings")
    require(settings.get("bindings", []) == [] and settings["compatibility_date"] == binding["compatibility_date"] and settings.get("compatibility_flags", []) == binding["compatibility_flags"], "worker_settings_drift")


def fenced(client, binding):
    inspect_worker(client, binding)
    value = client.request("GET", f"/builds/workers/{binding['worker_tag']}/triggers")
    triggers = value.get("triggers") if isinstance(value, dict) else value
    require(isinstance(triggers, list) and not triggers, "native_controller_not_fenced")
    seen = set()
    for page in range(1, 6):
        value = client.request("GET", f"/builds/workers/{binding['worker_tag']}/builds?per_page=200&page={page}")
        builds = value["builds"] if isinstance(value, dict) else value
        require(isinstance(builds, list), "build_inventory_shape")
        if not builds:
            return
        for build in builds:
            require(build["build_uuid"] not in seen and build["status"] == "stopped", "native_build_or_pagination_unsafe")
            seen.add(build["build_uuid"])
        info = getattr(client, "last_info", None)
        if isinstance(info, dict) and info.get("total_pages") == page and info.get("total_count") == len(seen):
            return
    raise Blocked("build_inventory_incomplete")


def upload(client, binding, files, run_id, source, bundle_digest):
    manifest = {}
    by_hash = {}
    config = {}
    for path, content in files.items():
        if path in {"_headers", "_redirects"}:
            require(len(content) <= 128 * 1024, "asset_rules_size")
            config[path] = content.decode("utf-8")
            continue
        extension = path.rsplit(".", 1)[-1] if "." in path else ""
        digest = hashlib.sha256(base64.b64encode(content) + extension.encode()).hexdigest()[:32]
        kind = mimetypes.guess_type(path)[0] or "application/octet-stream"
        require(digest not in by_hash or by_hash[digest] == (kind, content), "asset_hash_collision")
        by_hash[digest] = (kind, content)
        manifest["/" + path] = {"hash": digest, "size": len(content)}
    session = client.request("POST", f"/workers/scripts/{client.worker}/assets-upload-session", {"manifest": manifest})
    jwt = session["jwt"]
    require(isinstance(jwt, str) and 16 <= len(jwt) <= 16384, "asset_upload_token")
    client.secrets.append(jwt)
    buckets = session["buckets"]
    require(isinstance(buckets, list) and len(buckets) <= len(manifest), "asset_buckets")
    completion = jwt if not buckets else None
    uploaded = set()
    for bucket in buckets:
        require(isinstance(bucket, list) and bool(bucket), "asset_bucket_shape")
        parts = []
        for digest in bucket:
            require(digest in by_hash and digest not in uploaded, "asset_request_mismatch")
            uploaded.add(digest)
            kind, content = by_hash[digest]
            parts.append((digest, kind, base64.b64encode(content)))
        body, content_type = multipart(parts)
        result = client.request("POST", "/workers/assets/upload?base64=true", body, content_type, jwt)
        if result.get("jwt"):
            completion = result["jwt"]
            client.secrets.append(completion)
    require(isinstance(completion, str), "asset_upload_incomplete")
    metadata = {"assets": {"jwt": completion, "config": config}, "compatibility_date": binding["compatibility_date"], "compatibility_flags": binding["compatibility_flags"], "annotations": {"workers/message": f"GitHub run {run_id}; source {source}; bundle {bundle_digest}", "workers/tag": f"gha-{run_id}"}}
    body, content_type = multipart([("metadata", "application/json", json.dumps(metadata).encode())])
    version = client.request("POST", f"/workers/scripts/{client.worker}/versions", body, content_type)
    require(isinstance(version, dict) and re.fullmatch(r"[a-f0-9-]{36}", version.get("id", "")), "created_version_identity")
    return version["id"]


def promote(client, version):
    require(re.fullmatch(r"[a-f0-9-]{36}", version), "version_identity")
    return client.request("POST", f"/workers/scripts/{client.worker}/deployments", {"strategy": "percentage", "versions": [{"version_id": version, "percentage": 100}]})
