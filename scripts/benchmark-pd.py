#!/usr/bin/env python3
"""Run matched AIPerf workload sweeps on an existing two- or four-slot MPS cluster."""

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
MODES = ("aggregated", "disaggregated")
METRICS = {
    "output_tokens_per_second": "output_token_throughput",
    "requests_per_second": "request_throughput",
    "latency_avg_ms": "request_latency",
    "ttft_avg_ms": "time_to_first_token",
    "itl_avg_ms": "inter_token_latency",
    "input_tokens_avg": "input_sequence_length",
    "output_tokens_avg": "output_sequence_length",
    "duration_seconds": "benchmark_duration",
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def validate_config(config, scheduler="serial"):
    for key in ("input_tokens", "output_tokens", "concurrencies"):
        values = config[key]
        if not values or len(values) != len(set(values)) or any(type(v) is not int or v < 1 for v in values):
            raise ValueError(f"{key} must contain distinct positive integers")
    for key in ("requests", "warmup_requests", "dataset_entries", "repetitions"):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    limit = 32 if scheduler == "token-budget" else 8
    if max(config["concurrencies"]) > limit:
        raise ValueError(f"The {scheduler} router admits at most {limit} concurrent requests")
    if max(config["output_tokens"]) > 256 or max(config["input_tokens"]) > 704:
        raise ValueError("Workloads exceed the checked-in worker limits including chat template overhead")
    if config["requests"] < max(config["concurrencies"]):
        raise ValueError("requests must cover the largest concurrency")
    if type(config["seed"]) is not int or config["seed"] < 0:
        raise ValueError("seed must be a nonnegative integer")
    if config.get("mixed_distribution"):
        total = 0
        for pair in config["mixed_distribution"].split(";"):
            lengths, probability = pair.split(":")
            isl, osl = map(int, lengths.split(","))
            weight = float(probability)
            if not (1 <= isl <= 704 and 1 <= osl <= 256 and 0 < weight <= 100):
                raise ValueError("Invalid mixed workload lengths or probability")
            total += weight
        if not math.isclose(total, 100):
            raise ValueError("Mixed workload probabilities must sum to 100")


def profile(replicas, scheduler="serial"):
    if replicas not in (2, 4):
        raise ValueError("MPS replicas must be 2 or 4")
    if scheduler not in {"serial", "token-budget"} or (scheduler == "token-budget" and replicas != 4):
        raise ValueError("Token-budget scheduling requires the four-slot profile")
    selected = {"cluster": "local-k8s-gpu-mps" + ("4" if replicas == 4 else ""),
            "namespace": "pd-comparison" + ("-4" if replicas == 4 else ""),
            "workers": {"aggregated": replicas, "prefill": 1, "decode": replicas - 1}}
    prefix = f"mps-{replicas}"
    if scheduler == "token-budget":
        selected["namespace"] = "pd-comparison-4-scheduled"
        prefix += "-scheduled"
    selected["values"] = {mode: ROOT / "k8s/inference-distributed/profiles" / f"{prefix}-{mode}.yaml" for mode in MODES}
    return selected


def check_slots(nodes, replicas):
    workers = [n for n in nodes["items"] if int(n["status"]["allocatable"].get("nvidia.com/gpu.shared", 0))]
    if (len(workers) != 1 or int(workers[0]["status"]["allocatable"]["nvidia.com/gpu.shared"]) != replicas
            or workers[0]["metadata"].get("labels", {}).get("nvidia.com/mps.capable") != "true"):
        raise RuntimeError(f"Expected one MPS worker with exactly {replicas} slots on the selected cluster")


def job_manifest(template, config, group, name, artifact_path, namespace="pd-comparison"):
    job = deepcopy(template)
    job["metadata"]["name"] = name
    job["metadata"]["namespace"] = namespace
    job["spec"]["activeDeadlineSeconds"] = 7200
    job["spec"].pop("ttlSecondsAfterFinished", None)
    client = job["spec"]["template"]["spec"]["containers"][0]
    args = client["args"]
    replace = {"--request-count": config["requests"], "--warmup-request-count": config["warmup_requests"],
               "--random-seed": config["seed"], "--artifact-dir": artifact_path}
    for key, value in replace.items():
        args[args.index(key) + 1] = str(value)
    pos = args.index("--sequence-distribution")
    if group == "grid":
        del args[pos:pos + 2]
        args.extend(["--isl", ",".join(map(str, config["input_tokens"])),
                     "--osl", ",".join(map(str, config["output_tokens"])), "--sweep-type", "grid"])
    else:
        args[pos + 1] = config["mixed_distribution"]
    args.extend(["--no-gpu-telemetry", "--export-level", "records"])
    for env in client["env"]:
        if env["name"] == "CONCURRENCIES":
            env["value"] = ",".join(map(str, config["concurrencies"]))
        elif env["name"] == "DATASET_ENTRIES":
            env["value"] = str(config["dataset_entries"])
    return job


def collect_exports(directory, config, repetition, mode, group):
    rows = []
    for path in sorted(directory.rglob("profile_export_aiperf.json")):
        if "phases" in path.relative_to(directory).parts:
            continue
        data = json.loads(path.read_text())
        settings = data.get("input_config")
        if not settings:
            continue
        phase = next(p for p in settings["phases"] if p["name"] == "profiling")
        prompts = settings["datasets"][0]["prompts"]
        workload = "mixed" if group == "mixed" else f"i{int(prompts['isl']['mean'])}-o{int(prompts['osl']['mean'])}"
        value = lambda name: data.get(name, {}).get("avg")
        if data.get("was_cancelled") or data.get("error_summary") or (value("error_request_count") or 0):
            raise RuntimeError(f"Failed AIPerf requests in {path}")
        if value("request_count") != config["requests"]:
            raise RuntimeError(f"Unexpected request count in {path}")
        records = []
        for line in (path.parent / "profile_export.jsonl").read_text().splitlines():
            record = json.loads(line)
            if record["metadata"]["benchmark_phase"] == "profiling":
                records.append(record)
        if len(records) != config["requests"]:
            raise RuntimeError(f"Missing request records in {path}")
        for record in records:
            if record["metadata"].get("was_cancelled") or record.get("error"):
                raise RuntimeError(f"Failed request in {path}")
            if record["metrics"].get("osl_mismatch_diff_pct", {}).get("value") != 0:
                raise RuntimeError(f"Output token count differs from requested length in {path}")
        inputs = json.loads((path.parent / "inputs.json").read_text())
        payloads = [entry["payloads"] for entry in inputs["data"]]
        digest = hashlib.sha256(json.dumps(payloads, sort_keys=True).encode()).hexdigest()
        lengths = Counter((int(r["metrics"]["input_sequence_length"]["value"]),
                           int(r["metrics"]["output_sequence_length"]["value"])) for r in records)
        row = {"repetition": repetition, "mode": mode, "workload": workload,
               "concurrency": phase["concurrency"], "requests": len(records), "errors": 0,
               "dataset_sha256": digest, "length_counts": {f"{i}/{o}": n for (i, o), n in sorted(lengths.items())},
               "artifact": os.path.relpath(path, ROOT),
               **{key: value(metric) for key, metric in METRICS.items()}}
        row["latencies_ms"] = [r["metrics"]["request_latency"]["value"] for r in records]
        row["ttfts_ms"] = [r["metrics"]["time_to_first_token"]["value"] for r in records]
        if any(row[k] is None or not math.isfinite(row[k]) for k in METRICS):
            raise RuntimeError(f"Missing or non-finite metrics in {path}")
        rows.append(row)
    shapes = len(config["input_tokens"]) * len(config["output_tokens"]) if group == "grid" else 1
    if len(rows) != shapes * len(config["concurrencies"]):
        raise RuntimeError(f"Expected {shapes * len(config['concurrencies'])} exports, got {len(rows)} in {directory}")
    return rows


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["workload"], row["concurrency"], row["mode"])].append(row)
    output = []
    for (workload, concurrency, mode), group in sorted(groups.items()):
        result = {"workload": workload, "concurrency": concurrency, "mode": mode,
                  "repetitions": len(group), "requests": sum(r["requests"] for r in group),
                  "errors": sum(r["errors"] for r in group)}
        for name in METRICS:
            values = [r[name] for r in group]
            result[name] = statistics.mean(values)
            result[name + "_std"] = statistics.stdev(values) if len(values) > 1 else 0
        for name, key in (("latency_p95_ms", "latencies_ms"), ("ttft_p95_ms", "ttfts_ms")):
            values = sorted(v for row in group for v in row[key])
            result[name] = values[math.ceil(0.95 * len(values)) - 1]
        output.append(result)
    return output


def check_pairs(rows):
    pairs = defaultdict(dict)
    for row in rows:
        key = row["repetition"], row["workload"], row["concurrency"]
        if row["mode"] in pairs[key]:
            raise RuntimeError(f"Duplicate result: {key} {row['mode']}")
        pairs[key][row["mode"]] = row
    for key, pair in pairs.items():
        if set(pair) == set(MODES):
            for field in ("dataset_sha256", "length_counts", "requests"):
                if pair[MODES[0]][field] != pair[MODES[1]][field]:
                    raise RuntimeError(f"Unmatched {field}: {key}")


def check_workers(pods):
    for pod in pods["items"]:
        for container in pod.get("status", {}).get("containerStatuses", []):
            if container.get("restartCount", 0):
                reason = container.get("lastState", {}).get("terminated", {}).get("reason", "unknown")
                raise RuntimeError(f"Inference container restarted: {pod['metadata']['name']}/{container['name']}: {reason}")


def completed_repetitions(rows, config):
    workloads = [f"i{i}-o{o}" for i in config["input_tokens"] for o in config["output_tokens"]]
    if config.get("mixed_distribution"):
        workloads.append("mixed")
    expected = {(w, c, m) for w in workloads for c in config["concurrencies"] for m in MODES}
    groups = defaultdict(list)
    for row in rows:
        groups[row["repetition"]].append(row)
    selected = []
    for _, group in sorted(groups.items()):
        keys = [(r["workload"], r["concurrency"], r["mode"]) for r in group]
        if len(keys) == len(expected) and set(keys) == expected:
            check_pairs(group)
            selected.extend(group)
    if not selected:
        raise ValueError("No complete paired repetition covers every configured workload")
    return selected


def save(report, metadata, rows):
    summary = summarize(rows)
    write_json(report / "summary.json", {"metadata": metadata, "results": summary})
    if summary:
        with (report / "summary.csv").open("w") as output:
            writer = csv.DictWriter(output, fieldnames=list(summary[0]))
            writer.writeheader()
            writer.writerows(summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "benchmarks/pd.json")
    parser.add_argument("--mps-replicas", type=int, choices=(2, 4), default=os.environ.get("MPS_REPLICAS", "2"))
    parser.add_argument("--cluster", default=os.environ.get("CLUSTER_NAME"))
    parser.add_argument("--scheduler", choices=("serial", "token-budget"), default="serial")
    parser.add_argument("--token-budget", type=int, default=256)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--raw-dir", type=Path)
    args = parser.parse_args()
    if args.token_budget < 1:
        parser.error("--token-budget must be positive")
    topology = profile(args.mps_replicas, args.scheduler)
    args.cluster = args.cluster or topology["cluster"]
    config = json.loads(args.config.read_text())
    validate_config(config, args.scheduler)
    run_id = ("pd4-" if args.mps_replicas == 4 else "pd-") + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report = (args.report_dir or ROOT / "docs/reports/gpu/pd" / run_id).resolve()
    raw = (args.raw_dir or ROOT / "reports/pd" / run_id).resolve()
    report.mkdir(parents=True, exist_ok=False)
    raw.mkdir(parents=True, exist_ok=False)
    state = ROOT / ".local-k8s"
    state.mkdir(exist_ok=True)
    lock = (state / "benchmark.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    env = {**os.environ, "GPU_SHARING": "mps", "MPS_REPLICAS": str(args.mps_replicas), "CLUSTER_NAME": args.cluster,
           "PD_SCHEDULER": args.scheduler, "PD_TOKEN_BUDGET": str(args.token_budget)}

    def command(argv, **kwargs):
        return subprocess.run([str(a) for a in argv], cwd=ROOT, env=env, text=True,
                              capture_output=True, check=True, timeout=kwargs.pop("timeout", 180), **kwargs).stdout

    def kube(*argv, **kwargs):
        return command([ROOT / "scripts/local-k8s-gpu.sh", "kubectl", "-n", topology["namespace"], *argv], **kwargs)

    def apply(obj):
        obj = deepcopy(obj)
        obj["metadata"]["namespace"] = topology["namespace"]
        return kube("apply", "-f", "-", input=json.dumps(obj))

    metadata = {"status": "running", "run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(),
                "cluster": args.cluster, "config": config, "raw_dir": os.path.relpath(raw, ROOT),
                "model": "HuggingFaceTB/SmolLM2-135M-Instruct", "dtype": "float16", "mps_slots": args.mps_replicas,
                "namespace": topology["namespace"], "workers": topology["workers"],
                "scheduler": args.scheduler,
                "scheduler_config": ({"token_budget": args.token_budget, "max_num_seqs": 8,
                                      "max_kv_tokens": 8192} if args.scheduler == "token-budget" else None),
                "mps_active_thread_percentage": 100 // args.mps_replicas,
                "mode_order": [], "completed_groups": []}
    rows = []
    job_name = None
    reader_name = run_id + "-results"
    reader_created = False
    sources = [*sorted((ROOT / "src/huggingface/llama/inference_distributed").glob("*.py")),
               *sorted((ROOT / "src/inference").glob("*.py")),
               *sorted((ROOT / "src/huggingface/runtime").glob("*.py")),
               *sorted((ROOT / "src/huggingface/llama").glob("*.py")), ROOT / "src/Dockerfile.gpu"]
    metadata["source_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    save(report, metadata, rows)
    print(f"REPORT {report}", flush=True)
    try:
        nodes = json.loads(kube("get", "nodes", "-o", "json"))
        write_json(raw / "nodes.json", nodes)
        check_slots(nodes, args.mps_replicas)
        metadata["gpu"] = command(["nvidia-smi", "--query-gpu=name,uuid,driver_version,memory.total", "--format=csv,noheader"]).strip()
        manifests = list(yaml.safe_load_all(command([
            ROOT / "scripts/render-k8s.sh", ROOT / "k8s/aiperf/profiles/pd.yaml",
            "--set-string", "namespace=" + topology["namespace"],
        ])))
        pvc = next(m for m in manifests if m["kind"] == "PersistentVolumeClaim")
        template = next(m for m in manifests if m["kind"] == "Job")
        namespace = command([ROOT / "scripts/render-k8s.sh", topology["values"]["aggregated"],
                             "--show-only", "templates/namespace.yaml"])
        kube("apply", "-f", "-", input=namespace)
        apply(pvc)
        reader = next(m for m in manifests if m["kind"] == "Pod")
        reader["metadata"]["name"] = reader_name
        reader["spec"]["containers"][0].update(image="local/aiperf:0.12.0", imagePullPolicy="Never",
                                               command=["sleep", "infinity"])
        apply(reader)
        reader_created = True
        kube("wait", "--for=condition=Ready", "pod/" + reader_name, "--timeout=180s", timeout=200)
        for repetition in range(1, config["repetitions"] + 1):
            order = MODES if repetition % 2 else MODES[::-1]
            metadata["mode_order"].append(list(order))
            for mode in order:
                print(f"DEPLOY repetition={repetition} mode={mode}", flush=True)
                directory = raw / f"r{repetition}" / mode
                directory.mkdir(parents=True)
                log = command([ROOT / "scripts/deploy-pd.sh", mode], timeout=700)
                (directory / "deploy.log").write_text(log)
                (directory / "workloads.yaml").write_text(kube("get", "deployments,statefulsets,pods,configmaps", "-o", "yaml"))
                groups = ("grid", "mixed") if config.get("mixed_distribution") else ("grid",)
                for group in groups:
                    job_name = f"{run_id}-r{repetition}-{mode[0]}-{group}"
                    artifact = f"/results/{run_id}/r{repetition}/{mode}/{group}"
                    job = job_manifest(template, config, group, job_name, artifact, topology["namespace"])
                    write_json(directory / (group + "-job.json"), job)
                    print(f"START r{repetition} {mode} {group}", flush=True)
                    apply(job)
                    deadline, next_update = time.monotonic() + 7250, 0
                    while True:
                        status = json.loads(kube("get", "job", job_name, "-o", "json")).get("status", {})
                        conditions = {c["type"] for c in status.get("conditions", []) if c["status"] == "True"}
                        if conditions & {"Failed", "FailureTarget"}:
                            raise RuntimeError(f"Job failed: {job_name}: {status}")
                        if "Complete" in conditions:
                            check_workers(json.loads(kube("get", "pods", "-l", "app.kubernetes.io/part-of=pd-comparison", "-o", "json")))
                            break
                        if time.monotonic() > deadline:
                            raise TimeoutError(job_name)
                        sample = command(["nvidia-smi", "--query-gpu=timestamp,utilization.gpu,memory.used,temperature.gpu,power.draw,clocks.sm", "--format=csv,noheader,nounits"])
                        with (directory / (group + "-gpu.csv")).open("a") as output:
                            output.write(sample)
                        if time.monotonic() >= next_update:
                            check_workers(json.loads(kube("get", "pods", "-l", "app.kubernetes.io/part-of=pd-comparison", "-o", "json")))
                            progress = ""
                            try:
                                files = kube("exec", reader_name, "--", "find", artifact,
                                             "-name", "profile_export_aiperf.json").splitlines()
                                done = sum("/phases/" not in path for path in files)
                                progress = f": {done} cells exported"
                            except subprocess.CalledProcessError:
                                pass
                            print(f"RUNNING r{repetition} {mode} {group}{progress}", flush=True)
                            next_update = time.monotonic() + 60
                        time.sleep(5)
                    (directory / (group + "-aiperf.log")).write_text(kube("logs", "job/" + job_name, "--tail=-1"))
                    destination = directory / group
                    destination.mkdir()
                    kube("cp", f"{reader_name}:{artifact}/.", destination, timeout=300)
                    new_rows = collect_exports(destination, config, repetition, mode, group)
                    pods = json.loads(kube("get", "pods", "-l", "app.kubernetes.io/part-of=pd-comparison", "-o", "json"))
                    write_json(directory / (group + "-pods.json"), pods)
                    check_workers(pods)
                    memory = json.loads(kube("exec", "deployment/pd-router", "--", "python", "-c",
                        "import json; from pathlib import Path; "
                        "root=Path('/sys/fs/cgroup'); "
                        "print(json.dumps({name:(root/name).read_text().strip() if (root/name).exists() else None "
                        "for name in ('memory.current','memory.peak','memory.max','memory.events','cpu.stat')}))"))
                    write_json(directory / (group + "-router-cgroup.json"), memory)
                    rows.extend(new_rows)
                    write_json(raw / "runs.json", rows)
                    check_pairs(rows)
                    metadata["completed_groups"].append(f"r{repetition}/{mode}/{group}")
                    save(report, metadata, rows)
                    kube("delete", "job", job_name, "--wait=true")
                    job_name = None
                    print(f"DONE r{repetition} {mode} {group}: {len(new_rows)} cells, {sum(r['requests'] for r in new_rows)} requests", flush=True)
                (directory / "workers.log").write_text(kube("logs", "-l", "app.kubernetes.io/part-of=pd-comparison", "--prefix", "--tail=-1"))
        metadata.update(status="complete", finished_at=datetime.now(timezone.utc).isoformat(),
                        measured_requests=sum(r["requests"] for r in rows), errors=sum(r["errors"] for r in rows),
                        matched_payloads=True, matched_lengths=True)
    except BaseException as exc:
        metadata.update(status="failed", error=str(exc))
        if job_name:
            try:
                (raw / "failed-job.log").write_text(kube("logs", "job/" + job_name, "--tail=-1"))
                (raw / "failed-pods.yaml").write_text(kube("get", "pods", "-o", "yaml"))
                (raw / "failed-workers.log").write_text(kube("logs", "-l", "app.kubernetes.io/part-of=pd-comparison", "--prefix", "--tail=-1"))
                pods = json.loads(kube("get", "pods", "-l", "app.kubernetes.io/part-of=pd-comparison", "-o", "json"))
                for pod in pods["items"]:
                    for container in pod.get("status", {}).get("containerStatuses", []):
                        if container.get("restartCount", 0):
                            name = pod["metadata"]["name"]
                            (raw / f"{name}-{container['name']}-previous.log").write_text(
                                kube("logs", name, "-c", container["name"], "--previous", "--tail=-1"))
            except Exception as cleanup_error:
                metadata["cleanup_error"] = str(cleanup_error)
            finally:
                try:
                    kube("delete", "job", job_name, "--ignore-not-found=true", "--wait=true")
                except Exception as cleanup_error:
                    metadata["job_cleanup_error"] = str(cleanup_error)
        raise
    finally:
        save(report, metadata, rows)
        if reader_created:
            try:
                kube("delete", "pod", reader_name, "--ignore-not-found=true", "--wait=false")
            except Exception as cleanup_error:
                print(f"Reader cleanup failed: {cleanup_error}", file=sys.stderr)
        lock.close()
    print(f"COMPLETE {report / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
