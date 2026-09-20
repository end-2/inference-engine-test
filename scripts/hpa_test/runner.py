#!/usr/bin/env python3
"""Verify CPU HPA scaling under AIPerf load."""

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import gzip
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = "hpa-test"
ENGINE = "llama-base-metric"


def now():
    return datetime.now(timezone.utc).isoformat()


def condition(obj, name):
    return any(
        c["type"] == name and c["status"] == "True"
        for c in obj.get("status", {}).get("conditions", [])
    )


def summarize(objects):
    hpa = next(o for o in objects if o["kind"] == "HorizontalPodAutoscaler")
    deployment = next(
        o for o in objects
        if o["kind"] == "Deployment" and o["metadata"]["name"] == ENGINE
    )
    all_pods = [
        o for o in objects
        if o["kind"] == "Pod"
        and o["metadata"].get("labels", {}).get("app") == ENGINE
    ]
    pods = [p for p in all_pods if not p["metadata"].get("deletionTimestamp")]
    ready = {p["metadata"]["uid"] for p in pods if condition(p, "Ready")}
    endpoints = {
        e.get("targetRef", {}).get("uid")
        for o in objects if o["kind"] == "EndpointSlice"
        and o["metadata"].get("labels", {}).get("kubernetes.io/service-name") == ENGINE
        for e in o.get("endpoints", [])
        if e.get("conditions", {}).get("ready") is True
        and not e.get("conditions", {}).get("terminating", False)
    }
    cpu = next((
        m["resource"].get("current", {}).get("averageUtilization")
        for m in hpa.get("status", {}).get("currentMetrics", [])
        if m["type"] == "Resource" and m["resource"]["name"] == "cpu"
    ), None)
    return dict(
        at=now(), cpu_percent=cpu,
        scaling_active=condition(hpa, "ScalingActive"),
        desired=hpa.get("status", {}).get("desiredReplicas", 0),
        current=hpa.get("status", {}).get("currentReplicas", 0),
        deployment_replicas=deployment["spec"].get("replicas", 1),
        available=deployment.get("status", {}).get("availableReplicas", 0),
        pod_count=len(pods), terminating_pods=len(all_pods) - len(pods),
        ready_endpoints=len(ready & endpoints), ready_uids=sorted(ready & endpoints),
    )


def scaled_out(sample, initial_uids, target):
    return (
        sample["scaling_active"] and sample["cpu_percent"] is not None
        and sample["desired"] >= target and sample["current"] >= target
        and sample["deployment_replicas"] >= target
        and sample["available"] >= target and sample["ready_endpoints"] >= target
        and bool(set(sample["ready_uids"]) - set(initial_uids))
    )


def at_minimum(sample, minimum, cpu_target=None):
    return (
        sample["scaling_active"] and sample["cpu_percent"] is not None
        and (cpu_target is None or sample["cpu_percent"] < cpu_target)
        and sample["current"] == sample["desired"] == sample["deployment_replicas"]
        == sample["available"] == sample["ready_endpoints"] == sample["pod_count"]
        == minimum and sample["terminating_pods"] == 0
    )


def low_load_arguments(original, request_rate):
    arguments = []
    iterator = iter(original)
    for value in iterator:
        if value in ("--concurrency", "--request-rate", "--request-rate-mode", "--arrival-pattern"):
            next(iterator)
        else:
            arguments.append(value)
    return arguments + [
        "--concurrency", "1", "--request-rate", str(request_rate),
        "--request-rate-mode", "constant",
    ]


def request_counts(directory, after=None, before=None):
    paths = list(directory.rglob("profile_export.jsonl"))
    if not paths:
        raise RuntimeError("Missing AIPerf request records: " + str(directory))
    lower = int(datetime.fromisoformat(after).timestamp() * 1e9) if after else 0
    upper = int(datetime.fromisoformat(before).timestamp() * 1e9) if before else math.inf
    counts = dict(success=0, error=0, success_after_scale_in=0)
    for path in paths:
        for line in path.read_text().splitlines():
            record = json.loads(line)
            if record.get("error"):
                counts["error"] += 1
            else:
                counts["success"] += 1
                metadata = record["metadata"]
                if after and lower <= metadata["request_start_ns"] <= metadata["request_end_ns"] <= upper:
                    counts["success_after_scale_in"] += 1
    return counts


class Experiment:
    def __init__(self, args):
        self.args = args
        self.k = [str(ROOT / "scripts/local-k8s.sh"), "kubectl", "--request-timeout=20s"]
        self.ns = ["-n", NAMESPACE]
        self.state = {}
        self.load_started = False
        self.load_pod = None
        self.load_phase = None
        self.original_load_args = None
        self.load_config_changed = False

    def command(self, *args, timeout=45):
        return subprocess.check_output(self.k + list(args), text=True, timeout=timeout)

    def get(self, *args):
        return json.loads(self.command(*args))

    def preflight(self):
        nodes = self.get("get", "nodes", "-o", "json")["items"]
        if not all(condition(n, "Ready") for n in nodes):
            raise RuntimeError("All nodes must be Ready")
        for label in ("engine", "monitor"):
            if not any(n["metadata"].get("labels", {}).get("workload") == label for n in nodes):
                raise RuntimeError("Missing workload=" + label + " node")
        hpa = self.get(*self.ns, "get", "hpa", ENGINE, "-o", "json")
        spec = hpa["spec"]
        target = spec["scaleTargetRef"]
        metrics = spec["metrics"]
        if target != {"apiVersion": "apps/v1", "kind": "Deployment", "name": ENGINE} or (
            len(metrics) != 1 or metrics[0]["type"] != "Resource"
            or metrics[0]["resource"]["name"] != "cpu"
            or metrics[0]["resource"]["target"]["type"] != "Utilization"
        ):
            raise RuntimeError("Expected one CPU utilization metric targeting llama-base-metric")
        self.minimum = spec.get("minReplicas", 1)
        self.target = self.args.target_replicas or spec["maxReplicas"]
        self.cpu_target = metrics[0]["resource"]["target"]["averageUtilization"]
        if not self.minimum < self.target <= spec["maxReplicas"]:
            raise RuntimeError("Target replicas must be above minReplicas and at most maxReplicas")
        deployments = self.get(*self.ns, "get", "deployments", "-o", "json")["items"]
        by_name = {d["metadata"]["name"]: d for d in deployments}
        self.original_load_args = next(
            c["args"] for c in by_name["aiperf"]["spec"]["template"]["spec"]["containers"]
            if c["name"] == "aiperf"
        )
        for name in (ENGINE, "aiperf", "prometheus", "grafana", "kube-state-metrics", "grafana-renderer"):
            d = by_name[name]
            replicas = d["spec"].get("replicas", 1)
            if name in ("aiperf", "grafana-renderer"):
                if replicas != 0:
                    raise RuntimeError(name + " must have replicas=0 before starting")
                pods = self.get(*self.ns, "get", "pods", "-l", "app=" + name, "-o", "json")
                if pods["items"]:
                    raise RuntimeError("Wait for previous " + name + " Pods to terminate")
            elif replicas < 1 or d.get("status", {}).get("availableReplicas", 0) < replicas:
                raise RuntimeError(name + " is not fully available")
            for c in d["spec"]["template"]["spec"]["containers"]:
                resources = c.get("resources", {})
                if not {"cpu", "memory"} <= resources.get("requests", {}).keys() or (
                    resources["requests"] != resources.get("limits")
                ):
                    raise RuntimeError(name + " requires equal CPU/memory requests and limits")
        reader = self.get(*self.ns, "get", "pod", "aiperf-results", "-o", "json")
        if not condition(reader, "Ready"):
            raise RuntimeError("aiperf-results must be Ready")
        self.get("get", "--raw", f"/apis/metrics.k8s.io/v1beta1/namespaces/{NAMESPACE}/pods")
        replicas = f"{self.minimum} → {self.target}"
        if self.args.scenario == "scale-out-in":
            replicas += f" → {self.minimum}"
        print(f"kind-{self.args.cluster}: {self.args.scenario}, CPU {self.cpu_target}%, replicas {replicas}", flush=True)

    def save(self):
        path = self.raw / "run.tmp"
        path.write_text(json.dumps(self.state, indent=2) + "\n")
        path.replace(self.raw / "run.json")

    def mark(self, action):
        self.state[action] = now()
        self.save()
        print(action, self.state[action], flush=True)

    def sample(self, phase):
        objects = self.get(*self.ns, "get", "hpa,deployments,pods,endpointslices,events", "-o", "json")
        record = summarize(objects["items"])
        record["phase"] = phase
        with gzip.open(self.raw / "kubernetes-snapshots.jsonl.gz", "at") as f:
            f.write(json.dumps(dict(at=record["at"], phase=phase, objects=objects)) + "\n")
        with (self.raw / "observations.jsonl").open("a") as f:
            f.write(json.dumps(record) + "\n")
        print(f"{phase}: CPU={record['cpu_percent']}% desired={record['desired']} available={record['available']} endpoints={record['ready_endpoints']}", flush=True)
        return record

    def wait_for(self, phase, predicate, timeout, stable_seconds=0):
        deadline = time.monotonic() + timeout
        since = None
        stable_since = None
        while time.monotonic() < deadline:
            sample = self.sample(phase)
            if predicate(sample):
                if since is None:
                    since = time.monotonic()
                    stable_since = sample["at"]
                if time.monotonic() - since >= stable_seconds:
                    sample["stable_since"] = stable_since
                    return sample
            else:
                since = None
            time.sleep(5)
        raise RuntimeError(phase + " timed out; inspect observations.jsonl and Kubernetes events")

    def prometheus(self, endpoint, **params):
        path = f"/api/v1/namespaces/{NAMESPACE}/services/prometheus:9090/proxy/api/v1/"
        result = self.get("get", "--raw", path + endpoint + "?" + urlencode(params))
        if result.get("status") != "success":
            raise RuntimeError("Prometheus query failed: " + str(result))
        return result

    def configure_load(self, arguments):
        patch = {"spec": {"template": {"spec": {"containers": [
            {"name": "aiperf", "args": arguments},
        ]}}}}
        self.command(*self.ns, "patch", "deployment/aiperf", "--type=strategic", "-p", json.dumps(patch))

    def start_load(self, phase, arguments):
        self.load_phase = phase
        self.state["load_phases"][phase] = {"arguments": arguments}
        self.mark(phase + "_load_requested")
        self.load_config_changed = True
        self.configure_load(arguments)
        self.load_started = True
        self.command(*self.ns, "scale", "deployment/aiperf", "--replicas=1")
        self.command(*self.ns, "rollout", "status", "deployment/aiperf", "--timeout=180s", timeout=200)
        pods = self.get(*self.ns, "get", "pods", "-l", "app=aiperf", "-o", "json")["items"]
        self.load_pod = next(p["metadata"]["name"] for p in pods if not p["metadata"].get("deletionTimestamp"))
        self.state["load_phases"][phase]["pod"] = self.load_pod
        self.mark(phase + "_load_ready")

    def measure(self):
        baseline = self.wait_for("baseline", lambda s: at_minimum(s, self.minimum, self.cpu_target),
                                 self.args.timeout, stable_seconds=30)
        self.state["initial_uids"] = baseline["ready_uids"]
        self.mark("baseline_ready")
        self.start_load("high", self.original_load_args)
        self.wait_for("scale-out", lambda s: scaled_out(s, baseline["ready_uids"], self.target), self.args.timeout)
        self.mark("scale_out_observed")
        self.wait_for("high-hold", lambda s: scaled_out(s, baseline["ready_uids"], self.target), self.args.timeout, stable_seconds=self.args.hold_seconds)
        if self.args.scenario == "scale-out-in":
            self.mark("load_reduction_requested")
            self.stop_load()
            self.start_load("low", low_load_arguments(self.original_load_args, self.args.low_request_rate))
            self.wait_for("scale-in", lambda s: at_minimum(s, self.minimum, self.cpu_target), self.args.timeout)
            self.mark("scale_in_observed")
            held = self.wait_for("low-hold", lambda s: at_minimum(s, self.minimum),
                                 self.args.timeout, stable_seconds=self.args.hold_seconds)
            self.state["low_hold_started"] = held["stable_since"]
        self.mark("measurement_complete")

    def stop_load(self):
        if self.load_started:
            try:
                if self.load_pod:
                    (self.raw / f"aiperf-{self.load_phase}.log").write_text(
                        self.command(*self.ns, "logs", self.load_pod, "--timestamps")
                    )
            except Exception as exc:
                self.state.setdefault("log_errors", {})[self.load_phase] = str(exc)
            self.command(*self.ns, "scale", "deployment/aiperf", "--replicas=0")
            self.command(*self.ns, "wait", "--for=delete", "pod", "-l", "app=aiperf", "--timeout=150s", timeout=170)
            self.load_started = False
            self.mark(self.load_phase + "_load_stopped")
            self.load_pod = self.load_phase = None

    def collect(self):
        for phase, details in self.state["load_phases"].items():
            if "pod" not in details:
                continue
            destination = self.raw / "aiperf" / phase
            destination.parent.mkdir(exist_ok=True)
            self.command(*self.ns, "cp", "aiperf-results:/results/" + details["pod"], str(destination), timeout=180)
            details["requests"] = request_counts(
                destination, self.state.get("low_hold_started") if phase == "low" else None,
                self.state.get("measurement_complete"),
            )
        dashboard = json.loads((ROOT / "k8s/hpa-test/grafana/hpa.json").read_text())
        directory = self.raw / "prometheus"
        directory.mkdir(exist_ok=True)
        for panel in dashboard["panels"]:
            for target in panel["targets"]:
                data = self.prometheus("query_range", query=target["expr"], start=self.state["started"], end=now(), step="5s")
                (directory / f"panel-{panel['id']}-{target['refId']}.json").write_text(json.dumps(data) + "\n")
        records = [json.loads(line) for line in (self.raw / "observations.jsonl").read_text().splitlines()]
        with (self.raw / "observations.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[k for k in records[0] if k != "ready_uids"])
            writer.writeheader()
            writer.writerows({k: v for k, v in r.items() if k != "ready_uids"} for r in records)

    def verify_requests(self):
        phases = ("high", "low") if self.args.scenario == "scale-out-in" else ("high",)
        for phase in phases:
            if self.state["load_phases"][phase]["requests"]["success"] < 1:
                raise RuntimeError("No successful inference requests during " + phase + " load")
        if self.args.scenario == "scale-out-in" and self.state["load_phases"]["low"]["requests"]["success_after_scale_in"] < 1:
            raise RuntimeError("No low-load request started and completed during the scale-in hold")

    def execute(self):
        identifier = "hpa-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        self.raw = ROOT / "reports" / identifier
        self.raw.mkdir(parents=True)
        self.state = dict(id=identifier, scenario=self.args.scenario,
                          cluster=self.args.cluster, namespace=NAMESPACE,
                          status="running", min_replicas=self.minimum, target_replicas=self.target,
                          cpu_target=self.cpu_target, hold_seconds=self.args.hold_seconds,
                          low_request_rate=self.args.low_request_rate, load_phases={},
                          original_load_arguments=self.original_load_args)
        self.mark("started")
        error = None
        try:
            self.measure()
        except BaseException as exc:
            error = exc
        finally:
            try:
                self.stop_load()
            except Exception as exc:
                self.state["cleanup_error"] = str(exc)
                error = error or exc
            # Restore the high-load template only after the client has stopped.
            if self.load_config_changed and not self.load_started:
                try:
                    self.configure_load(self.original_load_args)
                    self.mark("load_configuration_restored")
                except Exception as exc:
                    self.state["restore_error"] = str(exc)
                    error = error or exc
            try:
                self.sample("load-stopped")
                self.collect()
                if error is None:
                    self.verify_requests()
            except Exception as exc:
                self.state["collection_error"] = str(exc)
                error = error or exc
            self.state["status"] = "failed" if error else "complete"
            if error:
                self.state["error"] = str(error) or type(error).__name__
            self.mark("finished")
            print(self.raw / "run.json", flush=True)
        if error:
            raise error


def parse_args(scenario, argv=None):
    descriptions = {
        "scale-out": "Verify CPU HPA scale-out and hold the target replicas under high AIPerf load.",
        "scale-out-in": "Verify CPU HPA scale-out, reduce AIPerf load, and verify scale-in.",
    }
    parser = argparse.ArgumentParser(description=descriptions[scenario])
    parser.set_defaults(scenario=scenario, low_request_rate=None)
    parser.add_argument("--cluster", default=os.environ.get("CLUSTER_NAME", "local-k8s"))
    parser.add_argument("--target-replicas", type=int, help="Default: HPA maxReplicas")
    parser.add_argument("--timeout", type=int, default=600, help="Deadline per phase in seconds")
    parser.add_argument("--hold-seconds", type=int, default=60)
    if scenario == "scale-out-in":
        parser.add_argument("--low-request-rate", type=float, default=0.02,
                            help="Low-load requests/second, concurrency=1, constant arrival (default: 0.02)")
    parser.add_argument("--dry-run", action="store_true", help="Read-only preflight")
    args = parser.parse_args(argv)
    if args.timeout <= 30 or not 0 < args.hold_seconds < args.timeout:
        parser.error("Require timeout > 30 and 0 < hold-seconds < timeout")
    if args.target_replicas is not None and args.target_replicas < 2:
        parser.error("target-replicas must be at least 2")
    if args.low_request_rate is not None and (not math.isfinite(args.low_request_rate) or args.low_request_rate <= 0):
        parser.error("low-request-rate must be finite and positive")
    return args


def main(scenario="scale-out-in"):
    args = parse_args(scenario)
    os.environ["CLUSTER_NAME"] = args.cluster
    kubeconfig = subprocess.check_output([str(ROOT / "scripts/local-k8s.sh"), "kubeconfig"], text=True).strip()

    def interrupted(signum, frame):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt("Signal " + str(signum))

    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    with (Path(kubeconfig).parent / "hpa-test.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        experiment = Experiment(args)
        experiment.preflight()
        if not args.dry_run:
            experiment.execute()


if __name__ == "__main__":
    main()
