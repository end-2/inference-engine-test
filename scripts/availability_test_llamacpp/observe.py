from datetime import datetime, timezone
from pathlib import Path
import gzip, json, subprocess, threading, time, sys

state = json.loads(Path(sys.argv[1]).read_text())
raw = Path(state["raw"])
kube = state["kube"]
stop = threading.Event()


def now():
    return datetime.now(timezone.utc).isoformat()


def call(args):
    p = subprocess.run(
        kube + ["--request-timeout=5s"] + args,
        text=True,
        capture_output=True,
        timeout=7,
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip())
    return json.loads(p.stdout)


def resources():
    with gzip.open(raw / "resources.jsonl.gz", "at") as f:
        while not (raw / "STOP").exists():
            for node in (state["monitor_node"], state["survivor_node"]):
                try:
                    record = {
                        "observed_at": now(),
                        "node": node,
                        "data": call(
                            [
                                "get",
                                "--raw",
                                f"/api/v1/nodes/{node}/proxy/stats/summary",
                            ]
                        ),
                    }
                except Exception as e:
                    record = {"observed_at": now(), "node": node, "error": str(e)}
                f.write(json.dumps(record) + "\n")
                f.flush()
            stop.wait(10)


def docker_states():
    with (raw / "docker-states.jsonl").open("a") as f:
        while not (raw / "STOP").exists():
            try:
                obj = json.loads(
                    subprocess.check_output(
                        ["docker", "inspect", state["victim_node"]],
                        text=True,
                        timeout=5,
                    )
                )[0]
                record = {
                    "observed_at": now(),
                    "state": obj["State"],
                    "restart_count": obj["RestartCount"],
                    "restart_policy": obj["HostConfig"]["RestartPolicy"],
                }
            except Exception as e:
                record = {"observed_at": now(), "error": str(e)}
            f.write(json.dumps(record) + "\n")
            f.flush()
            stop.wait(2)


thread = threading.Thread(target=resources, daemon=True)
thread.start()
docker_thread = threading.Thread(target=docker_states, daemon=True)
docker_thread.start()
previous = None
with gzip.open(raw / "kubernetes-snapshots.jsonl.gz", "at") as f, (
    raw / "state-changes.jsonl"
).open("a") as changes:
    while not (raw / "STOP").exists():
        tick = time.monotonic()
        try:
            data = call(
                [
                    "-n",
                    state["namespace"],
                    "get",
                    "nodes,pods,deployments,replicasets,endpointslices,events",
                    "-o",
                    "json",
                ]
            )
            record = {"observed_at": now(), "data": data}
            f.write(json.dumps(record) + "\n")
            f.flush()
            brief = {"nodes": {}, "pods": {}, "endpoints": {}, "deployment": {}}
            for obj in data["items"]:
                name = obj["metadata"]["name"]
                kind = obj["kind"]
                if kind == "Node":
                    brief["nodes"][name] = {
                        "conditions": {
                            x["type"]: x["status"]
                            for x in obj["status"].get("conditions", [])
                        },
                        "taints": obj["spec"].get("taints", []),
                    }
                elif (
                    kind == "Pod"
                    and obj["metadata"].get("labels", {}).get("app")
                    == "base-metric-llamacpp"
                ):
                    brief["pods"][name] = {
                        "node": obj["spec"].get("nodeName"),
                        "phase": obj["status"].get("phase"),
                        "ready": next(
                            (
                                x["status"]
                                for x in obj["status"].get("conditions", [])
                                if x["type"] == "Ready"
                            ),
                            None,
                        ),
                        "deleting": obj["metadata"].get("deletionTimestamp"),
                        "reason": obj["status"].get("reason"),
                        "uid": obj["metadata"]["uid"],
                        "created": obj["metadata"]["creationTimestamp"],
                    }
                elif kind == "EndpointSlice":
                    brief["endpoints"].setdefault(
                        obj["metadata"]["labels"]["kubernetes.io/service-name"], []
                    ).extend(
                        [
                            {
                                "pod": x.get("targetRef", {}).get("name"),
                                "node": x.get("nodeName"),
                                "conditions": x.get("conditions"),
                            }
                            for x in (obj.get("endpoints") or [])
                        ]
                    )
                elif kind == "Deployment" and name == "base-metric-llamacpp":
                    brief["deployment"] = {
                        k: v for k, v in obj["status"].items() if k != "conditions"
                    }
            (raw / "latest-state.tmp").write_text(
                json.dumps(
                    {"observed_at": record["observed_at"], "state": brief}, indent=2
                )
            )
            (raw / "latest-state.tmp").replace(raw / "latest-state.json")
            if brief != previous:
                change = {"observed_at": record["observed_at"], "state": brief}
                changes.write(json.dumps(change) + "\n")
                changes.flush()
                print(
                    json.dumps(
                        {
                            "time": record["observed_at"],
                            "pods": brief["pods"],
                            "ready_nodes": {
                                n: v["conditions"].get("Ready")
                                for n, v in brief["nodes"].items()
                            },
                        }
                    ),
                    flush=True,
                )
                previous = brief
        except Exception as e:
            f.write(json.dumps({"observed_at": now(), "error": str(e)}) + "\n")
            f.flush()
        stop.wait(max(0, 2 - (time.monotonic() - tick)))
stop.set()
thread.join(timeout=15)
print("Observation stopped", now(), flush=True)
