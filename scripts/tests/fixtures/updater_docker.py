from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

root = Path(__file__).parent
assert not any(key in os.environ for key in ["GH_TOKEN", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY"])
args = sys.argv[1:]
assert args[:3] == ["--host", "unix:///var/run/docker.sock", "--config"]
args = args[4:]
state = json.loads((root / "docker-state.json").read_text())
policy = json.loads((root / "runtime-policy.json").read_text())
state["events"].append(args)
result = ""
code = 0
containers = state["containers"]
if args[:2] == ["image", "inspect"]:
    result = json.dumps([json.loads((root / "image.json").read_text())])
elif args[:2] == ["network", "inspect"]:
    result = json.dumps([{"Id": policy["network_id"], "Name": policy["network"], "Driver": "bridge"}])
elif args[0] == "pull":
    result = "pulled"
elif args[0] == "inspect":
    selected = [value for key, value in containers.items() if key == args[1] or value["Name"] == "/" + args[1]]
    if selected:
        result = json.dumps(selected)
    else:
        code = 1
elif args[0] == "create":
    identifier = str(state["next"]) * 64
    state["next"] += 1
    option = lambda name: args[args.index(name) + 1]
    mount = dict(item.split("=", 1) for item in option("--mount").split(","))
    labels = dict(args[i + 1].split("=", 1) for i, arg in enumerate(args) if arg == "--label")
    network = option("--network")
    containers[identifier] = {"Id": identifier, "Name": "/" + option("--name"), "State": {"Running": False}, "Config": {"Image": args[-1], "User": option("--user"), "Labels": labels, "Entrypoint": ["/app/game-entrypoint.sh"], "Cmd": ["dotnet", "RNGWars.Api.dll"]}, "HostConfig": {"PortBindings": {}, "Init": True, "ReadonlyRootfs": True, "Privileged": False, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges"], "NetworkMode": network}, "Mounts": [{"Type": "bind", "Source": mount["src"], "Destination": "/data", "RW": True}], "NetworkSettings": {"Networks": {network: {"NetworkID": "", "Aliases": []}}}}
    result = identifier
    if state["fault"] == "ambiguous-create":
        code = 1
        result = ""
elif args[0] == "start":
    container = containers[args[1]]
    container["State"]["Running"] = True
    for name, settings in container["NetworkSettings"]["Networks"].items():
        if name == policy["network"]:
            settings["NetworkID"] = policy["network_id"]
    if state["fault"] == "candidate-schema" and container["HostConfig"]["NetworkMode"] == "none":
        with closing(sqlite3.connect(Path(container["Mounts"][0]["Source"]) / "game.sqlite3")) as db:
            db.execute("CREATE TABLE unsafe_migration(id INTEGER)")
    if state["fault"] == "live-data-change" and container["Id"] != policy["initial_container"] and container["Mounts"][0]["Source"] == str(Path(policy["database"]).parent):
        with closing(sqlite3.connect(policy["database"])) as db, db:
            db.execute("UPDATE users SET token='changed-at-startup'")
    result = args[1]
elif args[0] == "stop":
    containers[args[-1]]["State"]["Running"] = False
    result = args[-1]
elif args[0] == "rename":
    containers[args[1]]["Name"] = "/" + args[2]
elif args[:2] == ["network", "disconnect"]:
    containers[args[-1]]["NetworkSettings"]["Networks"] = {}
elif args[:2] == ["network", "connect"]:
    containers[args[-1]]["NetworkSettings"]["Networks"] = {policy["network"]: {"NetworkID": policy["network_id"], "Aliases": ["game"]}}
elif args[0] == "exec":
    container = containers[args[1]]
    live_new = container["Id"] != policy["initial_container"] and container["Mounts"][0]["Source"] == str(Path(policy["database"]).parent)
    if not container["State"]["Running"] or (state["fault"] == "live-health" and live_new):
        code = 1
    else:
        result = '{"status":"ok"}'
else:
    raise RuntimeError("unexpected fixture Docker operation")
(root / "docker-state.json").write_text(json.dumps(state))
if result:
    print(result)
if code:
    print("private-Docker-diagnostic", file=sys.stderr)
raise SystemExit(code)
