#!/usr/bin/env python3
"""Run one independent kind node-failure experiment and export observations."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "scripts/availability_test"
SCENARIOS = ("pause-300s", "sigkill-300s", "pause-60s", "sigkill-60s")


def now():
    return datetime.now(timezone.utc).isoformat()


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def output(args):
    return subprocess.check_output([str(x) for x in args], text=True, timeout=30)


def validate_target(node, container, cluster):
    labels = node["metadata"].get("labels", {})
    docker_labels = container["Config"].get("Labels", {})
    if (
        labels.get("workload") != "engine"
        or "node-role.kubernetes.io/control-plane" in labels
    ):
        raise RuntimeError("Fault target must be an engine worker")
    if (
        docker_labels.get("io.x-k8s.kind.cluster") != cluster
        or docker_labels.get("io.x-k8s.kind.role") != "worker"
    ):
        raise RuntimeError("Docker target is not a worker in the selected kind cluster")
    if not container["State"]["Running"] or container["State"]["Paused"]:
        raise RuntimeError("Target must be running and unpaused")


def policy_argument(policy):
    suffix = (
        ":" + str(policy["MaximumRetryCount"])
        if policy["Name"] == "on-failure" and policy["MaximumRetryCount"]
        else ""
    )
    return policy["Name"] + suffix


class Experiment:
    def __init__(self, args):
        self.args = args
        kubeconfig = output([ROOT / "scripts/local-k8s.sh", "kubeconfig"]).strip()
        kubectl = Path(os.environ.get("LOCAL_K8S_BIN_DIR", ROOT / ".bin")) / "kubectl"
        self.k = [
            str(kubectl),
            "--kubeconfig",
            kubeconfig,
            "--context",
            "kind-" + args.cluster,
        ]
        self.ns = ["-n", "availability-test"]
        self.mode, seconds = args.scenario.rsplit("-", 1)
        self.seconds = int(seconds[:-1])
        self.children = []
        self.observer = None
        self.fault_active = False
        self.policy = None
        self.s = None

    def get(self, args):
        return json.loads(output(self.k + args))

    def kubectl(self, *args):
        return run(self.k + list(args))

    def scale(self, name, replicas):
        self.kubectl(
            *self.ns, "scale", "deployment/" + name, "--replicas=" + str(replicas)
        )

    def preflight(self):
        nodes = self.get(["get", "nodes", "-o", "json"])["items"]
        for node in nodes:
            if not any(
                c["type"] == "Ready" and c["status"] == "True"
                for c in node["status"]["conditions"]
            ):
                raise RuntimeError("All nodes must be Ready before starting")
        engines = sorted(
            n["metadata"]["name"]
            for n in nodes
            if n["metadata"].get("labels", {}).get("workload") == "engine"
        )
        monitors = [
            n["metadata"]["name"]
            for n in nodes
            if n["metadata"].get("labels", {}).get("workload") == "monitor"
        ]
        if len(engines) != 2 or len(monitors) != 1:
            raise RuntimeError(
                "Requires exactly two engine workers and one monitor worker"
            )
        self.victim = self.args.victim_node or engines[0]
        if self.victim not in engines:
            raise RuntimeError("Selected victim is not an engine worker")
        self.survivor = next(n for n in engines if n != self.victim)
        self.monitor = monitors[0]
        node = next(n for n in nodes if n["metadata"]["name"] == self.victim)
        validate_target(
            node,
            json.loads(output(["docker", "inspect", self.victim]))[0],
            self.args.cluster,
        )
        for name in ("aiperf", "grafana-renderer"):
            if (
                self.get(self.ns + ["get", "deployment", name, "-o", "json"])["spec"][
                    "replicas"
                ]
                != 0
            ):
                raise RuntimeError(
                    name + " must have replicas=0 before an independent run"
                )
        for name in (
            "llama-base-metric",
            "prometheus",
            "grafana",
            "kube-state-metrics",
        ):
            d = self.get(self.ns + ["get", "deployment", name, "-o", "json"])
            if d["status"].get("availableReplicas", 0) < d["spec"]["replicas"]:
                raise RuntimeError(name + " is not fully available")
            for c in d["spec"]["template"]["spec"]["containers"]:
                r = c.get("resources", {})
                if not r.get("requests") or r.get("requests") != r.get("limits"):
                    raise RuntimeError(name + " must have requests equal to limits")
        self.get(self.ns + ["get", "pod", "aiperf-results", "-o", "json"])
        print(
            f"{self.args.scenario}: {self.victim} → {self.survivor}; isolated context kind-{self.args.cluster}",
            flush=True,
        )

    def save(self):
        temp = self.raw / "run.tmp"
        temp.write_text(json.dumps(self.s, indent=2) + "\n")
        temp.replace(self.raw / "run.json")

    def mark(self, key):
        self.s[key] = now()
        self.save()
        with (self.raw / "actions.jsonl").open("a") as f:
            f.write(json.dumps({"at": self.s[key], "action": key}) + "\n")
        print(key, self.s[key], flush=True)

    def spawn(self, args, logfile):
        with (self.raw / logfile).open("w") as f:
            p = subprocess.Popen(
                [str(x) for x in args], stdout=f, stderr=subprocess.STDOUT
            )
        self.children.append(p)
        return p

    def forward(self, service, remote):
        logfile = service + "-port-forward.log"
        p = self.spawn(
            self.k
            + self.ns
            + [
                "port-forward",
                "--address=127.0.0.1",
                "service/" + service,
                ":" + str(remote),
            ],
            logfile,
        )
        for _ in range(100):
            match = re.search(
                r"Forwarding from 127\.0\.0\.1:(\d+)", (self.raw / logfile).read_text()
            )
            if match:
                return "http://127.0.0.1:" + match[1]
            if p.poll() is not None:
                break
            time.sleep(0.1)
        raise RuntimeError("Port-forward failed: " + service)

    def snapshot(self, name):
        for suffix, args in [
            (
                "kubernetes",
                self.ns
                + [
                    "get",
                    "nodes,pods,deployments,replicasets,endpointslices,events",
                    "-o",
                    "json",
                ],
            ),
            ("pods", self.ns + ["get", "pods", "-o", "wide"]),
            ("nodes", ["get", "nodes", "-L", "workload"]),
        ]:
            (self.raw / f"{name}-{suffix}.txt").write_text(output(self.k + args))
        (self.raw / f"{name}-docker.json").write_text(
            output(["docker", "inspect", self.victim])
        )

    def reset_inference(self):
        self.scale("llama-base-metric", 0)
        self.kubectl(
            *self.ns,
            "wait",
            "--for=delete",
            "pod",
            "-l",
            "app=llama-base-metric",
            "--timeout=180s",
        )
        tolerations = [
            {
                "key": "node.kubernetes.io/" + key,
                "operator": "Exists",
                "effect": "NoExecute",
                "tolerationSeconds": self.seconds,
            }
            for key in ("not-ready", "unreachable")
        ]
        patch = {"spec": {"template": {"spec": {"tolerations": tolerations}}}}
        self.kubectl(
            *self.ns,
            "patch",
            "deployment/llama-base-metric",
            "--type=merge",
            "-p",
            json.dumps(patch),
        )
        self.scale("llama-base-metric", 2)
        self.kubectl(
            *self.ns,
            "rollout",
            "status",
            "deployment/llama-base-metric",
            "--timeout=180s",
        )
        pods = self.get(
            self.ns + ["get", "pods", "-l", "app=llama-base-metric", "-o", "json"]
        )["items"]
        if len(pods) != 2 or {p["spec"].get("nodeName") for p in pods} != {
            self.victim,
            self.survivor,
        }:
            raise RuntimeError(
                "Fresh inference replicas did not spread across both engine workers"
            )
        for p in pods:
            if p["status"].get("qosClass") != "Guaranteed":
                raise RuntimeError("Inference Pod does not have Guaranteed QoS")
            for required in tolerations:
                if required not in p["spec"]["tolerations"]:
                    raise RuntimeError(
                        "Pod tolerations do not match requested scenario"
                    )
        return pods

    def latest(self):
        x = json.loads((self.raw / "latest-state.json").read_text())
        if (
            datetime.now(timezone.utc) - datetime.fromisoformat(x["observed_at"])
        ).total_seconds() > 15:
            raise RuntimeError("Kubernetes observer is stale")
        return x["state"]

    def follow(self, pod):
        self.spawn(self.k + self.ns + ["logs", "-f", pod, "--timestamps"], pod + ".log")

    def recover(self):
        if self.fault_active:
            # Inspect actual state in case an interrupted command already recovered the node.
            state = json.loads(output(["docker", "inspect", self.victim]))[0]["State"]
            if state["Paused"]:
                run(["docker", "unpause", self.victim])
            if not state["Running"]:
                run(["docker", "start", self.victim])
            self.fault_active = False
            self.mark("safety_recovery")
        if self.policy is not None:
            run(
                [
                    "docker",
                    "update",
                    "--restart=" + policy_argument(self.policy),
                    self.victim,
                ]
            )
            self.policy = None
            self.mark("restart_policy_restored")

    def measure(self):
        pods = self.reset_inference()
        self.s["initial_pods"] = {
            p["metadata"]["name"]: p["spec"]["nodeName"] for p in pods
        }
        victim = next(p for p in pods if p["spec"]["nodeName"] == self.victim)
        self.s.update(
            victim_pod=victim["metadata"]["name"], victim_uid=victim["metadata"]["uid"]
        )
        self.snapshot("prepared")
        self.scale("aiperf", 1)
        self.kubectl(
            *self.ns, "rollout", "status", "deployment/aiperf", "--timeout=120s"
        )
        self.s["aiperf_pod"] = self.get(
            self.ns + ["get", "pods", "-l", "app=aiperf", "-o", "json"]
        )["items"][0]["metadata"]["name"]
        for pod in [*self.s["initial_pods"], self.s["aiperf_pod"]]:
            self.follow(pod)
        self.mark("warmup_started")
        time.sleep(90)
        if (
            "is PROFILING"
            not in (self.raw / (self.s["aiperf_pod"] + ".log")).read_text()
        ):
            raise RuntimeError("AIPerf did not start profiling")
        self.spawn(
            [
                "docker",
                "events",
                "--filter",
                "container=" + self.victim,
                "--format",
                "{{json .}}",
            ],
            "docker-events.jsonl",
        )
        self.mark("collection_start")
        self.observer = self.spawn(
            [sys.executable, HELPERS / "observe.py", self.raw / "run.json"],
            "observer.log",
        )
        time.sleep(150)
        st = self.latest()
        if len(st["pods"]) != 2 or not all(
            p["ready"] == "True" for p in st["pods"].values()
        ):
            raise RuntimeError("Baseline does not have two ready inference replicas")
        policy = json.loads(output(["docker", "inspect", self.victim]))[0][
            "HostConfig"
        ]["RestartPolicy"]
        self.s["original_restart_policy"] = policy
        if self.mode == "sigkill":
            self.policy = policy
            self.save()
            run(["docker", "update", "--restart=no", self.victim])
            self.mark("automatic_restart_disabled")
        self.snapshot("before-fault")
        self.mark("fault_requested")
        self.fault_active = True
        run(
            ["docker", "pause", self.victim]
            if self.mode == "pause"
            else ["docker", "kill", "--signal=SIGKILL", self.victim]
        )
        self.mark("fault_completed")
        self.snapshot("after-fault")
        state = json.loads(output(["docker", "inspect", self.victim]))[0]["State"]
        valid = (
            state["Paused"] and state["Running"]
            if self.mode == "pause"
            else state["Status"] == "exited"
            and state["ExitCode"] == 137
            and not state["Running"]
        )
        if not valid:
            raise RuntimeError("Docker did not enter the requested fault state")
        if self.mode == "sigkill":
            source = f"{self.victim}:/var/log/pods/availability-test_{self.s['victim_pod']}_{self.s['victim_uid']}/api/0.log"
            run(["docker", "cp", source, self.raw / "victim-server-container.log"])
        deadline = time.monotonic() + self.seconds + 180
        while time.monotonic() < deadline:
            st = self.latest()
            if (
                st["nodes"][self.victim]["conditions"]["Ready"] != "True"
                and "node_not_ready_observed" not in self.s
            ):
                self.mark("node_not_ready_observed")
                self.snapshot("node-not-ready")
            new = [
                n
                for n, p in st["pods"].items()
                if n not in self.s["initial_pods"]
                and p["ready"] == "True"
                and p["node"] == self.survivor
                and not p["deleting"]
            ]
            if new:
                self.s["replacement_pod"] = new[0]
                self.mark("replacement_ready_observed")
                self.follow(new[0])
                self.snapshot("replacement-ready")
                break
            time.sleep(1)
        else:
            raise RuntimeError("Replacement Pod readiness timed out")
        time.sleep(90)
        self.snapshot("before-recovery")
        self.mark("recover_requested")
        run(["docker", "unpause" if self.mode == "pause" else "start", self.victim])
        self.fault_active = False
        self.mark("recover_completed")
        self.kubectl(
            "wait", "--for=condition=Ready", "node/" + self.victim, "--timeout=180s"
        )
        self.mark("node_recovered_observed")
        time.sleep(90)
        self.snapshot("after-recovery")
        self.mark("experiment_complete")

    def collect(self):
        text = (self.raw / (self.s["aiperf_pod"] + ".log")).read_text()
        artifacts = [
            line.split("Starting AIPerf: ", 1)[1].strip()
            for line in text.splitlines()
            if "Starting AIPerf: " in line
        ]
        if len(artifacts) != 1:
            raise RuntimeError("Expected one continuous AIPerf window")
        self.s["aiperf_artifact_path"] = artifacts[0]
        self.save()
        self.kubectl(
            *self.ns, "cp", "aiperf-results:" + artifacts[0], str(self.raw / "aiperf")
        )
        logs = output(
            self.k
            + [
                "-n",
                "kube-system",
                "logs",
                "kube-controller-manager-" + self.args.cluster + "-control-plane",
                "--since-time=" + self.s["collection_start"],
                "--timestamps",
            ]
        )
        (self.raw / "kube-controller-manager.log").write_text(logs)
        run([sys.executable, HELPERS / "metrics.py", self.raw / "run.json"])

    def execute(self):
        identifier = (
            "availability-"
            + self.args.scenario
            + "-"
            + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        )
        self.raw = ROOT / "reports" / identifier
        self.raw.mkdir(parents=True)
        self.s = dict(
            id=identifier,
            root=str(ROOT),
            raw=str(self.raw),
            kube=self.k,
            namespace="availability-test",
            cluster=self.args.cluster,
            victim_node=self.victim,
            survivor_node=self.survivor,
            monitor_node=self.monitor,
            mode=self.mode,
            toleration_seconds=self.seconds,
            status="running",
        )
        self.mark("preparation_started")
        try:
            self.s["prometheus_url"] = self.forward("prometheus", 9090)
            self.save()
            try:
                self.measure()
            finally:
                self.recover()
                (self.raw / "STOP").touch()
                if self.observer is not None:
                    self.observer.wait(timeout=20)
                self.scale("aiperf", 0)
                self.kubectl(
                    *self.ns,
                    "wait",
                    "--for=delete",
                    "pod",
                    "-l",
                    "app=aiperf",
                    "--timeout=150s",
                )
            self.collect()
            self.reset_inference()
            self.snapshot("after-manual-reset")
            self.s["status"] = "complete"
            self.mark("completed")
            print(self.raw / "run.json", flush=True)
        except BaseException as exc:
            self.s["status"] = "failed"
            self.s["error"] = str(exc)
            self.save()
            raise
        finally:
            # A second attempt also covers exceptions during the measurement cleanup.
            try:
                self.recover()
            finally:
                for name in ("aiperf",):
                    try:
                        self.scale(name, 0)
                    except subprocess.CalledProcessError as exc:
                        print("Cleanup failed:", exc, file=sys.stderr)
                (self.raw / "STOP").touch()
                for child in reversed(self.children):
                    if child.poll() is None:
                        child.terminate()
                for child in self.children:
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, choices=SCENARIOS)
    parser.add_argument(
        "--cluster", default=os.environ.get("CLUSTER_NAME", "local-k8s")
    )
    parser.add_argument("--victim-node", help="Defaults to the first engine worker")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read-only preflight; does not scale, patch, or inject faults",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.cluster):
        parser.error("Invalid kind cluster name")
    os.environ["CLUSTER_NAME"] = args.cluster

    def interrupted(signum, frame):
        # Let cleanup complete if another termination signal arrives.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt("Signal " + str(signum))

    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    lockdir = ROOT / ".local-k8s" / args.cluster
    lockdir.mkdir(parents=True, exist_ok=True)
    with (lockdir / "availability-test.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        experiment = Experiment(args)
        experiment.preflight()
        if not args.dry_run:
            experiment.execute()


if __name__ == "__main__":
    main()
