import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "ghcr.io/example/game@sha256:" + "a" * 64


def compose_config(path, data_directory, **overrides):
    environment = {
        "PATH": os.environ["PATH"], "HOME": str(path.parent),
        "RNGWARS_GAME_IMAGE": IMAGE, "RNGWARS_DATA_DIRECTORY": str(data_directory),
        "RNGWARS_BIND_PORT": "40123", "RNGWARS_ALLOY_IMAGE": "grafana/alloy:fixture",
        "RNGWARS_DNS_RESOLVER": "127.0.0.1", "OBSERVABILITY_PROJECT": "fixture-project",
        **overrides,
    }
    result = subprocess.run(["docker", "compose", "--env-file", "/dev/null", "-f", str(path), "config", "--format", "json"], env=environment, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def render(template, values, directory):
    encoded = json.dumps(json.dumps(values)).replace("${", "$${")
    expression = f'jsonencode(templatefile({json.dumps(str(template))}, jsondecode({encoded})))'
    result = subprocess.run(["tofu", "console"], cwd=directory, env={"PATH": os.environ["PATH"], "HOME": str(directory)}, input=expression, text=True, capture_output=True, check=True)
    return json.loads(json.loads(result.stdout))


class DeploymentTests(unittest.TestCase):
    def test_bootstrap_stages_identical_helpers_and_compose_without_starting_services(self):
        with tempfile.TemporaryDirectory() as directory:
            area = Path(directory)
            installation = {key: str(area / key) for key in ["helper_directory", "data_directory", "credentials_directory", "state_directory", "compose_directory"]}
            variables = {"hostname": "fixture-host", "installation": installation, "production_compose": (ROOT / "ops/production/docker-compose.yml").read_text()}
            files = {"backup_script": "scripts/sqlite-backup.py", "backup_policy": "scripts/backup_policy.py", "backup_schedule_script": "scripts/sqlite-backup-schedule.py", "backup_timer": "ops/production/backup-schedule/rngwars-sqlite-backup.timer"}
            variables.update({key: (ROOT / path).read_text() for key, path in files.items()})
            variables["backup_service"] = render(ROOT / "ops/production/backup-schedule/rngwars-sqlite-backup.service", installation, area)
            cloud = yaml.safe_load(render(ROOT / "infra/cloud-init.yml", variables, area))
            staged = cloud["write_files"]
            compose = next(item for item in staged if item["path"].endswith("docker-compose.yml"))
            path = area / "compose.yml"
            path.write_text(compose["content"])
            self.assertEqual(compose_config(path, area / "data")["services"]["game"], compose_config(ROOT / "ops/production/docker-compose.yml", area / "data")["services"]["game"])
            for key, relative in files.items():
                item = next(item for item in staged if item["path"].endswith(Path(relative).name))
                self.assertEqual(item["content"].rstrip(), variables[key].rstrip())
                self.assertEqual(item["owner"], "root:root")
                self.assertNotIn(int(item["permissions"], 8) & 0o022, [0o002, 0o020, 0o022])
            commands = json.dumps(cloud["runcmd"])
            for forbidden in ["docker compose", "systemctl", "tailscale up", "curl", "restic init", "GHCR_TOKEN"]:
                self.assertNotIn(forbidden, commands)
            service = area / "rngwars-sqlite-backup.service"
            service.write_text(variables["backup_service"])
            timer = area / "rngwars-sqlite-backup.timer"
            timer.write_text(variables["backup_timer"])
            verified = subprocess.run(["systemd-analyze", "verify", str(service), str(timer)], capture_output=True, text=True)
            self.assertEqual(verified.returncode, 0, verified.stderr)

    def test_entrypoint_and_runtime_identity_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "created"
            subprocess.run(["sh", str(ROOT / "ops/production/game-entrypoint.sh"), "sh", "-c", 'printf safe > "$1"', "sh", str(path)], check=True)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        dockerfile = (ROOT / "Dockerfile").read_text()
        for required in ["USER 10001:10001", 'ENTRYPOINT ["/app/game-entrypoint.sh"]', 'CMD ["dotnet", "RNGWars.Api.dll"]']:
            self.assertIn(required, dockerfile)

    def test_compose_keeps_existing_storage_immutable_image_and_no_updater(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            configuration = compose_config(ROOT / "ops/production/docker-compose.yml", data)
            game = configuration["services"]["game"]
            self.assertEqual(game["image"], IMAGE)
            self.assertEqual(game["user"], "10001:10001")
            self.assertEqual(game["environment"]["ASPNETCORE_ENVIRONMENT"], "Production")
            self.assertEqual(game["environment"]["DATABASE_PATH"], "/data/game.sqlite3")
            self.assertEqual(game["volumes"], [{"type": "bind", "source": str(data), "target": "/data", "bind": {"create_host_path": False}}])
            self.assertEqual(game["ports"][0]["host_ip"], "127.0.0.1")
            self.assertEqual(game["labels"]["com.centurylinklabs.watchtower.enable"], "false")
            self.assertNotIn("watchtower", configuration["services"])
            self.assertFalse(data.exists())
            for key in ["RNGWARS_GAME_IMAGE", "RNGWARS_DATA_DIRECTORY", "RNGWARS_BIND_PORT"]:
                with self.subTest(key=key), self.assertRaises(subprocess.CalledProcessError):
                    compose_config(ROOT / "ops/production/docker-compose.yml", data, **{key: ""})


if __name__ == "__main__":
    unittest.main()
