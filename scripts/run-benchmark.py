#!/usr/bin/env python3
"""Build/load images as needed and benchmark a freshly restarted deployment per concurrency."""

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE_LABEL = "io.local.inference.source-sha256"


def run(*args, capture=False, check=True):
    result = subprocess.run([str(arg) for arg in args], text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if check and result.returncode:
        raise RuntimeError(f"Command failed: {' '.join(map(str, args))}\n{result.stderr or ''}")
    return result


def kube(*args, **kwargs):
    return run(ROOT / "scripts/local-k8s.sh", "kubectl", *args, **kwargs)


def kube_json(*args):
    return json.loads(kube(*args, "-o", "json", capture=True).stdout)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def source_hash(context):
    digest = hashlib.sha256()
    for path in sorted(context.rglob("*")):
        if any(part in {".git", "__pycache__"} for part in path.relative_to(context).parts):
            continue
        if path.is_file():
            digest.update(str(path.relative_to(context)).encode() + b"\0")
            digest.update(str(path.stat().st_mode & 0o777).encode() + b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def image_loaded(node, image, info):
    inspected = run("docker", "exec", node, "crictl", "inspecti", image,
                    capture=True, check=False)
    if inspected.returncode:
        return False
    status = json.loads(inspected.stdout)["status"]
    if status["id"] == info["Id"]:
        return True
    # Docker's containerd store exposes a manifest ID, while CRI reports
    # the config ID. Compare containerd's tag target for this store.
    digest = (info.get("Descriptor") or {}).get("digest")
    if not digest:
        return False
    images = run("docker", "exec", node, "ctr", "-n", "k8s.io", "images", "ls", capture=True).stdout
    return any(len(fields) >= 3 and fields[0] in status.get("repoTags", []) and fields[2] == digest
               for fields in (line.split() for line in images.splitlines()))


def ensure_image(image, context):
    inspected = run("docker", "image", "inspect", image, capture=True, check=False)
    info = json.loads(inspected.stdout)[0] if inspected.returncode == 0 else None
    fingerprint = source_hash(context) if context else None
    labels = ((info or {}).get("Config") or {}).get("Labels") or {}
    if context and (not info or labels.get(SOURCE_LABEL) != fingerprint):
        print(f"Building {image} from {context}", flush=True)
        run("docker", "build", "--label", f"{SOURCE_LABEL}={fingerprint}", "-t", image, context)
        info = json.loads(run("docker", "image", "inspect", image, capture=True).stdout)[0]
    elif not info:
        raise RuntimeError(f"Local image missing: {image}. Pull/build it first, or supply --build-context.")
    else:
        print(f"Reusing built image: {image} ({info['Id']})", flush=True)
    nodes = kube_json("get", "nodes")["items"]
    missing = []
    for node in nodes:
        name = node["metadata"]["name"]
        if not image_loaded(name, image, info):
            missing.append(name)
    if missing:
        print(f"Loading {image}: {', '.join(missing)}", flush=True)
        run(ROOT / "scripts/local-k8s.sh", "load-image", image)
        if not all(image_loaded(node["metadata"]["name"], image, info) for node in nodes):
            raise RuntimeError(f"Loaded image does not match the host image: {image}")
    else:
        print(f"Reusing loaded image on every node: {image}", flush=True)
    return {"image": image, "id": info["Id"], "source_sha256": fingerprint,
            "build_context": str(context) if context else None}


def render(path):
    output = kube("create", "--dry-run=client", "--validate=false", "-f", path,
                  "-o", "json", capture=True).stdout
    decoder = json.JSONDecoder()
    items = []
    while output.strip():
        item, end = decoder.raw_decode(output.lstrip())
        items.append(item)
        output = output.lstrip()[end:]
    if len(items) == 1:
        return items[0]
    return {"apiVersion": "v1", "kind": "List", "items": items}


def deployment_pods(deployment):
    selector = deployment["spec"]["selector"]
    if selector.get("matchExpressions"):
        raise RuntimeError("Benchmark deployment must use a matchLabels selector.")
    labels = ",".join(f"{key}={value}" for key, value in sorted(selector["matchLabels"].items()))
    return kube_json("get", "pods", "-l", labels)["items"]


class ResourceSampler:
    """Retain kubelet counters and their source timestamps alongside request exports."""

    columns = ("sampled_at", "node", "scope", "role", "pod", "pod_uid", "container",
               "cpu_time", "cpu_usage_core_nanoseconds", "cpu_cores", "cpu_percent_one_core",
               "cpu_interval_cores", "memory_time", "memory_working_set_bytes",
               "memory_usage_bytes", "memory_rss_bytes")

    def __init__(self, directory, nodes, inference_uid, job_name, namespace="default"):
        self.directory = directory
        self.nodes = nodes
        self.inference_uid = inference_uid
        self.job_name = job_name
        self.namespace = namespace
        self.previous = {}
        self.counts = {"inference": 0, "aiperf": 0}
        self.samples = 0
        with (directory / "resources.csv").open("w", newline="") as output:
            csv.DictWriter(output, fieldnames=self.columns).writeheader()

    def role(self, pod):
        ref = pod["podRef"]
        if ref["uid"] == self.inference_uid:
            return "inference"
        if ref["namespace"] == self.namespace and ref["name"].startswith(self.job_name + "-"):
            return "aiperf"
        return None

    def row(self, sampled_at, node, scope, role, stats, pod=None, container=""):
        ref = (pod or {}).get("podRef", {})
        cpu, memory = stats.get("cpu", {}), stats.get("memory", {})
        cores = cpu.get("usageNanoCores")
        cores = cores / 1e9 if cores is not None else None
        counter, timestamp = cpu.get("usageCoreNanoSeconds"), cpu.get("time")
        interval_cores = None
        key = (node, scope, ref.get("uid"), container)
        if counter is not None and timestamp:
            current = (datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp(), counter)
            previous = self.previous.get(key)
            if previous and current[0] > previous[0] and counter >= previous[1]:
                interval_cores = (counter - previous[1]) / ((current[0] - previous[0]) * 1e9)
            if previous is None or current[0] > previous[0]:
                self.previous[key] = current
        return dict(zip(self.columns, (
            sampled_at, node, scope, role, ref.get("name", ""), ref.get("uid", ""), container,
            timestamp, counter, cores, cores * 100 if cores is not None else None, interval_cores,
            memory.get("time"), memory.get("workingSetBytes"), memory.get("usageBytes"), memory.get("rss"))))

    def sample(self):
        for node in self.nodes:
            sampled_at = datetime.now(timezone.utc).isoformat()
            started = time.monotonic()
            try:
                response = kube("get", "--raw", f"/api/v1/nodes/{node}/proxy/stats/summary",
                                "--request-timeout=10s", capture=True)
                data = json.loads(response.stdout)
                pods = [pod for pod in data.get("pods", []) if self.role(pod)]
                raw = {"sampled_at": sampled_at, "collection_seconds": time.monotonic() - started,
                       "node": data["node"], "pods": pods}
            except Exception as exc:
                with (self.directory / "resources.jsonl").open("a") as output:
                    output.write(json.dumps({"sampled_at": sampled_at, "node_name": node,
                                             "error": str(exc)}) + "\n")
                raise RuntimeError(f"Resource collection failed for {node}: {exc}") from exc
            with (self.directory / "resources.jsonl").open("a") as output:
                output.write(json.dumps(raw, ensure_ascii=False) + "\n")
            rows = [self.row(sampled_at, node, "node", "node", data["node"])]
            for pod in pods:
                role = self.role(pod)
                if pod.get("cpu", {}).get("usageCoreNanoSeconds") is not None:
                    self.counts[role] += 1
                rows.append(self.row(sampled_at, node, "pod", role, pod, pod))
                for container in pod.get("containers", []):
                    rows.append(self.row(sampled_at, node, "container", role, container, pod, container["name"]))
            with (self.directory / "resources.csv").open("a", newline="") as output:
                csv.DictWriter(output, fieldnames=self.columns).writerows(rows)
            self.samples += 1

    def validate(self):
        if not all(self.counts.values()):
            raise RuntimeError(f"Missing resource samples for a benchmark Pod: {self.counts}")
        return {"node_samples": self.samples, "pod_cpu_samples": self.counts}


def export_requests(source, destination):
    rows = []
    for line in source.read_text().splitlines():
        record = json.loads(line)
        row = dict(record["metadata"])
        for name, item in record.get("metrics", {}).items():
            unit = re.sub(r"[^a-zA-Z0-9]+", "_", item.get("unit") or "").strip("_")
            row[f"{name}_{unit}" if unit else name] = item.get("value")
        rows.append({key: json.dumps(value) if isinstance(value, (dict, list)) else value
                     for key, value in row.items()})
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with destination.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def wait_job(name, timeout, sampler=None, sample_interval=5):
    deadline = time.monotonic() + timeout + 30
    while time.monotonic() < deadline:
        if sampler:
            sampler.sample()
        job = kube_json("get", "job", name)
        for condition in job.get("status", {}).get("conditions", []):
            if condition["status"] == "True":
                if condition["type"] in {"Failed", "FailureTarget"}:
                    raise RuntimeError(f"Job {name} failed: {condition.get('message', condition.get('reason'))}")
                if condition["type"] == "Complete":
                    return
        time.sleep(sample_interval)
    raise RuntimeError(f"Job {name} did not complete within {timeout}s")


def metric(data, name, stat="avg"):
    return (data.get(name) or {}).get(stat)


def collect_summary(path, concurrency):
    data = json.loads(path.read_text())
    if data.get("was_cancelled") or data.get("error_summary") or (metric(data, "error_request_count") or 0):
        raise RuntimeError(f"AIPerf reported cancelled/failed requests: {path}")
    count = metric(data, "request_count")
    if not count or count <= 0:
        raise RuntimeError(f"AIPerf produced no successful requests: {path}")
    return {"concurrency": concurrency, "requests": count,
            "output_tokens_per_second": metric(data, "output_token_throughput"),
            "requests_per_second": metric(data, "request_throughput"),
            "ttft_avg_ms": metric(data, "time_to_first_token"),
            "ttft_p95_ms": metric(data, "time_to_first_token", "p95"),
            "itl_avg_ms": metric(data, "inter_token_latency"),
            "itl_p95_ms": metric(data, "inter_token_latency", "p95"),
            "decode_avg_ms": metric(data, "decode_duration"),
            "decode_p95_ms": metric(data, "decode_duration", "p95"),
            "prefill_tokens_per_second_per_user": metric(data, "prefill_throughput_per_user"),
            "latency_avg_ms": metric(data, "request_latency"),
            "latency_p95_ms": metric(data, "request_latency", "p95")}


def validate_output_lengths(path):
    checked = overruns = 0
    with path.open() as records:
        for line in records:
            record = json.loads(line)
            if record["metadata"]["benchmark_phase"] != "profiling":
                continue
            difference = record["metrics"].get("osl_mismatch_diff_pct", {}).get("value")
            if difference is None:
                raise RuntimeError(f"Missing output-length comparison in {path}")
            if difference < 0:
                raise RuntimeError(f"Output ended before the requested length: {path}")
            checked += 1
            overruns += difference > 0
    return {"checked_requests": checked, "shortfalls": 0, "overruns": overruns}


def save_summary(report, metadata, rows):
    write_json(report / "run.json", metadata)
    if not rows:
        return
    with (report / "summary.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (report / "summary.jsonl").open("w") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
    lines = ["# AIPerf CPU benchmark", "", f"- Image: `{metadata['inference']['image']}`",
             f"- Image ID: `{metadata['inference']['id']}`", f"- Started (UTC): {metadata['started_at']}",
             f"- Status: {metadata['status']}",
             "- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.", "",
             "| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        values = [row[key] for key in ("concurrency", "requests", "output_tokens_per_second",
                  "ttft_avg_ms", "ttft_p95_ms", "itl_avg_ms", "itl_p95_ms",
                  "decode_avg_ms", "decode_p95_ms", "prefill_tokens_per_second_per_user",
                  "latency_avg_ms")]
        lines.append("| " + " | ".join(f"{value:.2f}" if isinstance(value, float) else str(value)
                                      for value in values) + " |")
    lines += ["", "Raw AIPerf exports, request CSV, resource JSONL/CSV, and logs are under each `c<concurrency>/` directory.",
              "`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings."]
    (report / "summary.md").write_text("\n".join(lines) + "\n")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=os.environ.get("INFERENCE_IMAGE", "local/llama-base:0.1.0"))
    parser.add_argument("--build-context", default=os.environ.get("INFERENCE_CONTEXT", str(ROOT / "src/base")),
                        help="Empty string reuses a prebuilt local image without building")
    parser.add_argument("--manifests", default=os.environ.get("INFERENCE_MANIFESTS", str(ROOT / "k8s/llama-base")))
    parser.add_argument("--deployment", default=os.environ.get("INFERENCE_DEPLOYMENT", "llama-base"))
    parser.add_argument("--container", default=os.environ.get("INFERENCE_CONTAINER", "api"))
    parser.add_argument("--api-url", default=os.environ.get("API_URL", "http://llama-base:8000"))
    parser.add_argument("--model", default=os.environ.get("SERVED_MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct"))
    parser.add_argument("--concurrencies", default="1,2,4,8")
    parser.add_argument("--benchmark-image", default=f"local/aiperf:{os.environ.get('AIPERF_IMAGE_TAG', '0.12.0')}")
    parser.add_argument("--job-timeout", type=int, default=3600)
    parser.add_argument("--ready-timeout", type=int, default=300)
    parser.add_argument("--sample-interval", type=float, default=5,
                        help="Seconds between resource samples (plus collection time)")
    parser.add_argument("--reports-dir", type=Path, default=ROOT / "docs/reports")
    args = parser.parse_args()
    try:
        args.concurrencies = [int(value) for value in args.concurrencies.split(",")]
        if not args.concurrencies or min(args.concurrencies) < 1 or len(set(args.concurrencies)) != len(args.concurrencies):
            raise ValueError
    except ValueError:
        parser.error("concurrencies must be distinct positive integers")
    if min(args.job_timeout, args.ready_timeout) < 1:
        parser.error("timeouts must be positive")
    if not 0 < args.sample_interval <= 60:
        parser.error("sample interval must be between 0 and 60 seconds")
    args.build_context = Path(args.build_context).resolve() if args.build_context else None
    if args.build_context and not (args.build_context / "Dockerfile").is_file():
        parser.error("build context must contain a Dockerfile")
    args.manifests = Path(args.manifests).resolve()
    if not args.manifests.exists():
        parser.error("inference manifests do not exist")
    return args


def main():
    args = parse_args()
    state = Path(os.environ.get("LOCAL_K8S_STATE_DIR", ROOT / ".local-k8s"))
    state.mkdir(parents=True, exist_ok=True)
    lock = (state / "benchmark.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        print("Another benchmark runner is active in this state directory.", file=sys.stderr)
        return 1
    started = datetime.now(timezone.utc)
    run_id = "bench-" + started.strftime("%Y%m%d-%H%M%S-%f")
    name = re.sub(r"[^a-zA-Z0-9_.-]", "-", args.image)
    report = args.reports_dir.resolve() / f"{run_id}-{name}"
    report.mkdir(parents=True)
    metadata = {"run_id": run_id, "started_at": started.isoformat(), "status": "running",
                "concurrencies": args.concurrencies, "sample_interval_seconds": args.sample_interval,
                "conditions": []}
    rows = []
    job_name = None
    case_dir = None
    print(f"Reports: {report}", flush=True)
    try:
        run(ROOT / "scripts/download-model.sh")
        run(ROOT / "scripts/download-tokenizer.sh")
        run(ROOT / "scripts/local-k8s.sh", "up")
        active = kube_json("get", "jobs", "-l", "benchmark=aiperf-cpu")["items"]
        if any(item.get("status", {}).get("active", 0) for item in active):
            raise RuntimeError("An AIPerf Job is already active; wait for it before restarting the server.")
        metadata["inference"] = ensure_image(args.image, args.build_context)
        metadata["benchmark"] = ensure_image(args.benchmark_image, ROOT / "src/aiperf")
        nodes = kube_json("get", "nodes")
        write_json(report / "nodes.json", nodes)
        manifests = render(args.manifests)
        items = manifests.get("items", [manifests])
        deployment = next(item for item in items if item["kind"] == "Deployment"
                          and item["metadata"]["name"] == args.deployment)
        if deployment["spec"].get("replicas", 1) != 1:
            raise RuntimeError("Benchmark requires one inference replica.")
        container = next(item for item in deployment["spec"]["template"]["spec"]["containers"]
                         if item["name"] == args.container)
        container["image"] = args.image
        path = report / "inference.json"
        write_json(path, manifests)
        kube("apply", "-f", path)
        kube("rollout", "status", f"deployment/{args.deployment}", f"--timeout={args.ready_timeout}s")
        kube("apply", "-f", ROOT / "k8s/aiperf/results.yaml")
        kube("wait", "--for=condition=Ready", "pod/aiperf-results", f"--timeout={args.ready_timeout}s")
        template = render(ROOT / "k8s/aiperf/job.yaml")
        for concurrency in args.concurrencies:
            case_dir = report / f"c{concurrency}"
            case_dir.mkdir()
            before = {pod["metadata"]["uid"] for pod in deployment_pods(deployment)}
            print(f"Restarting {args.deployment} before concurrency={concurrency}", flush=True)
            kube("rollout", "restart", f"deployment/{args.deployment}")
            kube("rollout", "status", f"deployment/{args.deployment}", f"--timeout={args.ready_timeout}s")
            pods = [pod for pod in deployment_pods(deployment) if not pod["metadata"].get("deletionTimestamp")]
            if len(pods) != 1 or pods[0]["metadata"]["uid"] in before:
                raise RuntimeError("Expected exactly one newly restarted inference Pod.")
            write_json(case_dir / "inference-pod.json", pods[0])
            condition = {"concurrency": concurrency, "pod_uid": pods[0]["metadata"]["uid"],
                         "pod_name": pods[0]["metadata"]["name"], "status": "running"}
            metadata["conditions"].append(condition)
            job = json.loads(json.dumps(template))
            job_name = f"{run_id}-c{concurrency}"
            job["metadata"]["name"] = job_name
            job["spec"]["activeDeadlineSeconds"] = args.job_timeout
            client = job["spec"]["template"]["spec"]["containers"][0]
            client["image"] = args.benchmark_image
            for env in client["env"]:
                if env["name"] in {"CONCURRENCIES", "API_URL", "MODEL_ID"}:
                    env["value"] = {"CONCURRENCIES": str(concurrency), "API_URL": args.api_url,
                                    "MODEL_ID": args.model}[env["name"]]
            artifact_path = f"/results/{run_id}/c{concurrency}"
            client["args"][client["args"].index("--artifact-dir") + 1] = artifact_path
            write_json(case_dir / "job.json", job)
            sampler = ResourceSampler(case_dir, [node["metadata"]["name"] for node in nodes["items"]],
                                      condition["pod_uid"], job_name)
            sampler.sample()
            condition["started_at"] = datetime.now(timezone.utc).isoformat()
            save_summary(report, metadata, rows)
            kube("create", "-f", case_dir / "job.json")
            print(f"Measuring concurrency={concurrency}: {job_name}", flush=True)
            wait_job(job_name, args.job_timeout, sampler, args.sample_interval)
            write_json(case_dir / "aiperf-pods.json", kube_json("get", "pods", "-l", f"job-name={job_name}"))
            (case_dir / "aiperf.log").write_text(kube("logs", f"job/{job_name}", capture=True).stdout)
            kube("cp", f"aiperf-results:{artifact_path}/.", case_dir / "artifacts")
            result = case_dir / "artifacts/profile_export_aiperf.json"
            export_requests(result.parent / "profile_export.jsonl", case_dir / "requests.csv")
            condition["resource_collection"] = sampler.validate()
            row = collect_summary(result, concurrency)
            expected = int(client["args"][client["args"].index("--request-count") + 1])
            if row["requests"] != expected:
                raise RuntimeError(f"Expected {expected} successful requests, got {row['requests']}")
            condition["output_length_check"] = validate_output_lengths(result.parent / "profile_export.jsonl")
            if condition["output_length_check"]["checked_requests"] != expected:
                raise RuntimeError("Per-request output records are incomplete")
            rows.append(row)
            condition["status"] = "complete"
            condition["completed_at"] = datetime.now(timezone.utc).isoformat()
            save_summary(report, metadata, rows)
            print(f"Completed concurrency={concurrency}: {result}", flush=True)
            job_name = None
        metadata["status"] = "complete"
        print(f"Completed benchmark: {report / 'summary.md'}", flush=True)
    except (Exception, KeyboardInterrupt) as exc:
        metadata["status"] = "failed"
        metadata["error"] = str(exc) or "Interrupted"
        if metadata["conditions"] and metadata["conditions"][-1]["status"] == "running":
            metadata["conditions"][-1]["status"] = "failed"
        if job_name and case_dir:
            for command, filename in [(('logs', f'job/{job_name}'), 'aiperf.log'),
                                      (('describe', 'job', job_name), 'job-diagnostics.txt')]:
                result = kube(*command, capture=True, check=False)
                (case_dir / filename).write_text(result.stdout + result.stderr)
            kube("delete", "job", job_name, "--ignore-not-found=true", check=False)
            if (case_dir / "job.json").exists():
                kube("cp", f"aiperf-results:/results/{run_id}/{case_dir.name}/.",
                     case_dir / "artifacts", check=False)
        print(f"Benchmark failed: {exc}\nDiagnostics: {report}", file=sys.stderr)
        return 1
    finally:
        metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
        save_summary(report, metadata, rows)
        lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
