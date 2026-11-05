import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).parent
binding = json.loads((root / "native-binding.json").read_text())
args = sys.argv[1:]
assert args[:3] == ["--host", "unix:///var/run/docker.sock", "--config"]
operation = args[4:]
mapping_path = root / "native-mapping.json"
mapping = json.loads(mapping_path.read_text())
real = binding["docker"]
if operation[0] == "pull":
    assert operation[-1] == binding["new_reference"]
    print("native fixture uses the already built image")
    raise SystemExit(0)
if operation[:2] == ["image", "inspect"]:
    result = subprocess.run([real, "image", "inspect", binding["image_id"]], capture_output=True, check=True)
    values = json.loads(result.stdout)
    values[0]["Id"] = binding["digest"]
    values[0]["Descriptor"] = {"digest": binding["digest"]}
    print(json.dumps(values))
    raise SystemExit(0)
if operation[0] == "create":
    reference = args[-1]
    assert reference == binding["new_reference"]
    args[-1] = binding["image_id"]
    result = subprocess.run([real, *args], capture_output=True)
    if result.returncode == 0:
        identifier = result.stdout.decode().strip()
        mapping[identifier] = reference
        mapping_path.write_text(json.dumps(mapping))
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    raise SystemExit(result.returncode)
result = subprocess.run([real, *args], capture_output=True)
if operation[0] == "inspect" and result.returncode == 0:
    values = json.loads(result.stdout)
    for value in values:
        value["Config"]["Image"] = mapping.get(value["Id"], value["Config"]["Image"])
    print(json.dumps(values))
else:
    sys.stdout.buffer.write(result.stdout)
if operation[0] == "start" and result.returncode == 0 and binding.get("fail_live"):
    value = json.loads(subprocess.check_output([real, "inspect", operation[1]]))[0]
    if value["Name"].startswith("/rngwars-game-next-"):
        subprocess.run([real, "kill", value["Id"]], capture_output=True, check=True)
sys.stderr.buffer.write(result.stderr)
raise SystemExit(result.returncode)
