#!/usr/bin/env python3
"""Build/load images as needed and benchmark a freshly restarted deployment per concurrency."""

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE_LABEL = "io.local.inference.source-sha256"
CACHE_POLICIES = ("preserve", "clear-before-sweep", "clear-per-concurrency")
CONTROL_PLANE_TOLERATION = {"key": "node-role.kubernetes.io/control-plane",
                           "operator": "Exists", "effect": "NoSchedule"}
CLEAR_CACHE_SCRIPT = """
import json
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
if not root.is_mount() or root.is_symlink() or root == Path('/'):
    raise RuntimeError('Cache directory must be a mounted PVC root')
entries = list(root.iterdir())
files = [path for path in root.rglob('*') if path.is_file() and not path.is_symlink()]
result = {'directory': str(root), 'removed_entries': len(entries),
          'removed_files': len(files), 'removed_bytes': sum(path.stat().st_size for path in files)}
for path in entries:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
result['remaining_entries'] = len(list(root.iterdir()))
if result['remaining_entries']:
    raise RuntimeError('Cache directory is not empty after cleanup')
print(json.dumps(result), flush=True)
"""


def run(*args, capture=False, check=True):
    result = subprocess.run([str(arg) for arg in args], text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if check and result.returncode:
        raise RuntimeError(f"Command failed: {' '.join(map(str, args))}\n{result.stderr or ''}")
    return result


def cluster_script():
    return Path(os.environ.get("LOCAL_K8S_SCRIPT", ROOT / "scripts/local-k8s.sh"))


def kube(*args, **kwargs):
    return run(cluster_script(), "kubectl", *args, **kwargs)


def kube_json(*args):
    return json.loads(kube(*args, "-o", "json", capture=True).stdout)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def source_hash(context, target=None):
    digest = hashlib.sha256()
    if target:
        digest.update(b"target\0" + target.encode() + b"\0")
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
    try:
        data = json.loads(inspected.stdout)
        status = data.get("status", data)
        if status.get("id") == info["Id"]:
            return True
    except (ValueError, AttributeError, KeyError):
        return False
    descriptor = info.get("Descriptor") or {}
    # kind imports the platform manifest, which can differ from Docker's index ID.
    if descriptor.get("mediaType") in {
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    }:
        platform = "/".join(info[key] for key in ("Os", "Architecture", "Variant") if info.get(key))
        selected = json.loads(run("docker", "image", "inspect", "--platform", platform,
                                  image, capture=True).stdout)[0]
        descriptor = selected.get("Descriptor") or {}
        if status.get("id") == selected["Id"]:
            return True
    digest = descriptor.get("digest")
    if not digest:
        return False
    images = run("docker", "exec", node, "ctr", "-n", "k8s.io", "images", "ls", capture=True).stdout
    references = {image, image if image.startswith("docker.io/") else f"docker.io/{image}"}
    for line in images.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] in references and fields[2] == digest:
            return True
    return False


def ensure_image(image, context, target=None, load_nodes=None):
    inspected = run("docker", "image", "inspect", image, capture=True, check=False)
    info = json.loads(inspected.stdout)[0] if inspected.returncode == 0 else None
    if info is None and context is None and load_nodes:
        ids = []
        for node in load_nodes:
            result = run("docker", "exec", node, "crictl", "inspecti", image,
                         capture=True, check=False)
            if result.returncode:
                raise RuntimeError(f"Image missing from host and node {node}: {image}")
            status = json.loads(result.stdout).get("status", {})
            image_id = status.get("id")
            if not image_id:
                raise RuntimeError(f"Node {node} returned no image ID for {image}")
            ids.append(image_id)
        if len(set(ids)) != 1:
            raise RuntimeError(f"Image ID differs across selected nodes: {image}")
        print(f"Reusing image loaded on selected nodes: {image} ({ids[0]})", flush=True)
        return {"image": image, "id": ids[0], "source_sha256": None,
                "build_context": None, "build_target": None}
    fingerprint = source_hash(context, target) if context else None
    labels = ((info or {}).get("Config") or {}).get("Labels") or {}
    if context and (not info or labels.get(SOURCE_LABEL) != fingerprint):
        print(f"Building {image} from {context}", flush=True)
        target_args = ("--target", target) if target else ()
        gpu_build = bool(target and target.endswith("-gpu"))
        dockerfile = ("-f", context / "Dockerfile.gpu") if gpu_build else ()
        cache_args = () if gpu_build else ("--no-cache",)
        run("docker", "build", *cache_args, *dockerfile, *target_args,
            "--label", f"{SOURCE_LABEL}={fingerprint}", "-t", image, context)
        info = json.loads(run("docker", "image", "inspect", image, capture=True).stdout)[0]
    elif not info:
        raise RuntimeError(f"Local image missing: {image}. Pull/build it first, or supply --build-context.")
    else:
        print(f"Reusing built image: {image} ({info['Id']})", flush=True)
    nodes = kube_json("get", "nodes")["items"]
    if load_nodes is not None:
        available = {node["metadata"]["name"] for node in nodes}
        if not load_nodes or not set(load_nodes) <= available:
            raise RuntimeError("Image load nodes must exist in this cluster")
        nodes = [node for node in nodes if node["metadata"]["name"] in load_nodes]
    missing = []
    for node in nodes:
        name = node["metadata"]["name"]
        if not image_loaded(name, image, info):
            missing.append(name)
    if missing:
        print(f"Loading {image}: {', '.join(missing)}", flush=True)
        # Remove stale node cache to ensure kind reload is not considered a no-op (no-cache for load)
        for node in missing:
            run("docker", "exec", node, "crictl", "rmi", image, capture=True, check=False)
            run("docker", "exec", node, "ctr", "-n", "k8s.io", "images", "rm", image, capture=True, check=False)
        if load_nodes is None:
            run(cluster_script(), "load-image", image)
        else:
            for node in missing:
                run(cluster_script(), "load-image-node", node, image)
        if not all(image_loaded(node["metadata"]["name"], image, info) for node in nodes):
            raise RuntimeError(f"Loaded image does not match the host image: {image}")
    else:
        print(f"Reusing loaded image on selected nodes: {image}", flush=True)
    return {"image": image, "id": info["Id"], "source_sha256": fingerprint,
            "build_context": str(context) if context else None,
            "build_target": target if context else None}


def render(path):
    path = Path(path)
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


def cache_volume(deployment, container):
    arguments = container.get("args", [])
    paths = [arguments[index + 1] for index, value in enumerate(arguments[:-1])
             if value == "--cache-dir"]
    paths += [value.split("=", 1)[1] for value in arguments if value.startswith("--cache-dir=")]
    if len(paths) != 1:
        raise RuntimeError("Cache clearing requires one explicit --cache-dir in the inference arguments.")
    directory = paths[0]
    path = PurePosixPath(directory)
    if not path.is_absolute() or path == PurePosixPath("/") or ".." in path.parts:
        raise RuntimeError("Cache directory must be an absolute non-root path without '..'.")
    mounts = [mount for mount in container.get("volumeMounts", []) if mount["mountPath"] == directory]
    if len(mounts) != 1 or any(mounts[0].get(key) for key in ("readOnly", "subPath", "subPathExpr")):
        raise RuntimeError("Cache directory must equal a writable, dedicated PVC mount root.")
    mount = mounts[0]
    volume = next(item for item in deployment["spec"]["template"]["spec"].get("volumes", [])
                  if item["name"] == mount["name"])
    if "persistentVolumeClaim" not in volume or volume["persistentVolumeClaim"].get("readOnly"):
        raise RuntimeError("Cache clearing requires a writable PVC volume.")
    return {"directory": directory, "mount": mount, "volume": volume,
            "pvc": volume["persistentVolumeClaim"]["claimName"]}


def clears_cache(policy, condition_index):
    return policy == "clear-per-concurrency" or (policy == "clear-before-sweep" and condition_index == 0)


def clear_pvc_cache(deployment, container, cache, name, directory, timeout):
    """Stop the writer before deleting cache files, including its shutdown flush."""
    target = f"deployment/{deployment['metadata']['name']}"
    pod_spec = deployment["spec"]["template"]["spec"]
    cleaner_spec = {"restartPolicy": "Never", "automountServiceAccountToken": False,
                    "securityContext": pod_spec.get("securityContext", {}),
                    "containers": [{"name": "clear-cache", "image": container["image"],
                                    "imagePullPolicy": container.get("imagePullPolicy", "IfNotPresent"),
                                    "command": ["python", "-c", CLEAR_CACHE_SCRIPT, cache["directory"]],
                                    "securityContext": container.get("securityContext", {}),
                                    "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                                                  "limits": {"cpu": "100m", "memory": "128Mi"}},
                                    "volumeMounts": [cache["mount"]]}],
                    "volumes": [cache["volume"]]}
    for key in ("nodeSelector", "affinity", "tolerations", "imagePullSecrets", "runtimeClassName"):
        if key in pod_spec:
            cleaner_spec[key] = pod_spec[key]
    job = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name},
           "spec": {"backoffLimit": 0, "activeDeadlineSeconds": timeout,
                    "template": {"spec": cleaner_spec}}}
    manifest = directory / "cache-clear-job.json"
    write_json(manifest, job)
    created = False
    kube("scale", target, "--replicas=0")
    try:
        deadline = time.monotonic() + timeout
        while deployment_pods(deployment):
            if time.monotonic() >= deadline:
                raise RuntimeError("Inference Pods did not terminate before cache clearing.")
            time.sleep(1)
        consumers = [pod["metadata"]["name"] for pod in kube_json("get", "pods")["items"]
                     if pod.get("status", {}).get("phase") not in {"Succeeded", "Failed"}
                     and any(volume.get("persistentVolumeClaim", {}).get("claimName") == cache["pvc"]
                             for volume in pod["spec"].get("volumes", []))]
        if consumers:
            raise RuntimeError(f"Cache PVC is still used by Pods: {', '.join(consumers)}")
        kube("create", "-f", manifest)
        created = True
        wait_job(name, timeout)
        result = json.loads(kube("logs", f"job/{name}", capture=True).stdout)
        if result["remaining_entries"] != 0 or result["directory"] != cache["directory"]:
            raise RuntimeError("Cache cleanup did not confirm an empty cache directory.")
        result.update(pvc=cache["pvc"], completed_at=datetime.now(timezone.utc).isoformat())
        write_json(directory / "cache-clear.json", result)
        return result
    finally:
        if created:
            logs = kube("logs", f"job/{name}", capture=True, check=False)
            (directory / "cache-clear.log").write_text(logs.stdout + logs.stderr)
            # Wait for the cleaner to exit before allowing a cache writer to start.
            kube("delete", "job", name, "--cascade=foreground", "--wait=true", f"--timeout={timeout}s")
        kube("scale", target, "--replicas=1")


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


class GPUSampler:
    columns = ("sampled_at", "uuid", "utilization_pct", "memory_used_mib", "memory_total_mib")

    def __init__(self, directory):
        self.path = directory / "gpu.csv"
        self.rows = []
        with self.path.open("w", newline="") as output:
            csv.DictWriter(output, fieldnames=self.columns).writeheader()

    def sample(self):
        output = run("nvidia-smi", "--query-gpu=uuid,utilization.gpu,memory.used,memory.total",
                     "--format=csv,noheader,nounits", capture=True).stdout.strip().splitlines()
        if len(output) != 1:
            raise RuntimeError("GPU benchmark requires exactly one visible host GPU")
        fields = [part.strip() for part in output[0].split(",")]
        if len(fields) != 4:
            raise RuntimeError("Invalid nvidia-smi GPU sample")
        row = dict(zip(self.columns, (datetime.now(timezone.utc).isoformat(), fields[0],
                                      float(fields[1]), float(fields[2]), float(fields[3]))))
        if self.rows and row["uuid"] != self.rows[0]["uuid"]:
            raise RuntimeError("GPU UUID changed during measurement")
        self.rows.append(row)
        with self.path.open("a", newline="") as output:
            csv.DictWriter(output, fieldnames=self.columns).writerow(row)

    def summary(self):
        if not self.rows or max(row["memory_used_mib"] for row in self.rows) <= 0:
            raise RuntimeError("No GPU memory use was observed during measurement")
        return {"gpu_uuid": self.rows[0]["uuid"], "gpu_samples": len(self.rows),
                "gpu_utilization_avg_pct": sum(row["utilization_pct"] for row in self.rows) / len(self.rows),
                "gpu_utilization_max_pct": max(row["utilization_pct"] for row in self.rows),
                "gpu_memory_used_avg_mib": sum(row["memory_used_mib"] for row in self.rows) / len(self.rows),
                "gpu_memory_used_max_mib": max(row["memory_used_mib"] for row in self.rows)}


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


def wait_job(name, timeout, sampler=None, sample_interval=5, gpu_sampler=None):
    deadline = time.monotonic() + timeout + 30
    while time.monotonic() < deadline:
        if sampler:
            sampler.sample()
        if gpu_sampler:
            gpu_sampler.sample()
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
    cache_policy = metadata.get("cache_policy", "preserve")
    cache_description = {
        "preserve": "no PVC cache deletion",
        "clear-before-sweep": "clear once before the first condition's warmup",
        "clear-per-concurrency": "clear before each condition's warmup",
    }[cache_policy]
    device = metadata.get("device", "cpu")
    lines = [f"# AIPerf {device.upper()} benchmark", "", f"- Image: `{metadata['inference']['image']}`",
             f"- Image ID: `{metadata['inference']['id']}`", f"- Started (UTC): {metadata['started_at']}",
             f"- Status: {metadata['status']}",
             f"- Device: `{device}`; compute setting: `{metadata.get('compute_setting', '')}`.",
             f"- PVC cache policy: `{cache_policy}` ({cache_description}).",
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
    if device == "gpu":
        lines += ["", "| Concurrency | GPU UUID | Samples | GPU avg (%) | GPU max (%) | Memory avg (MiB) | Memory max (MiB) |",
                  "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
        for row in rows:
            lines.append(f"| {row['concurrency']} | {row['gpu_uuid']} | {row['gpu_samples']} | "
                         f"{row['gpu_utilization_avg_pct']:.2f} | {row['gpu_utilization_max_pct']:.2f} | "
                         f"{row['gpu_memory_used_avg_mib']:.2f} | {row['gpu_memory_used_max_mib']:.2f} |")
    lines += ["", "Full AIPerf exports, request CSV, resource JSONL/CSV, GPU CSV when selected, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.",
              "`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings."]
    (report / "summary.md").write_text("\n".join(lines) + "\n")


def normalize_backend(backend):
    return "llamacpp" if backend == "llama" else backend


def variant_name(backend, variant="base"):
    if backend == "mamba":
        return f"transformers-mamba-{variant}"
    return f"transformers-{variant}" if backend == "transformers" else f"{variant}-llamacpp"


def image_name(backend, variant, device):
    name = variant_name(backend, variant)
    return f"{name}-gpu" if device == "gpu" else name


def manifests_path(backend, variant, device):
    directory = ROOT / "k8s"
    if device == "gpu":
        directory /= "gpu"
    return directory / variant_name(backend, variant)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("llamacpp", "transformers", "mamba"), type=normalize_backend,
                        default=os.environ.get("INFERENCE_BACKEND", "transformers"))
    parser.add_argument("--device", choices=("cpu", "gpu"), default=os.environ.get("BENCHMARK_DEVICE", "cpu"))
    parser.add_argument("--image", default=os.environ.get("INFERENCE_IMAGE"))
    parser.add_argument("--build-context", default=os.environ.get("INFERENCE_CONTEXT", str(ROOT / "src")),
                        help="Empty string reuses a prebuilt local image without building")
    parser.add_argument("--build-target", default=os.environ.get("INFERENCE_TARGET"),
                        help="Docker build stage; defaults to base for the shared src context")
    parser.add_argument("--manifests", default=os.environ.get("INFERENCE_MANIFESTS"))
    parser.add_argument("--deployment", default=os.environ.get("INFERENCE_DEPLOYMENT"))
    parser.add_argument("--container", default=os.environ.get("INFERENCE_CONTAINER", "api"))
    parser.add_argument("--api-url", default=os.environ.get("API_URL"))
    parser.add_argument("--model", default=os.environ.get("SERVED_MODEL_NAME"))
    parser.add_argument("--concurrencies", default="1,2,4,8")
    parser.add_argument("--cache-policy", choices=CACHE_POLICIES,
                        default=os.environ.get("BENCHMARK_CACHE_POLICY", "preserve"),
                        help="Preserve PVC cache, clear once before the sweep, or clear before every condition's warmup")
    parser.add_argument("--inference-node", help="Pin inference and cache cleanup to this Kubernetes node")
    parser.add_argument("--benchmark-node", help="Pin AIPerf to this Kubernetes node")
    parser.add_argument("--benchmark-image", default=f"local/aiperf:{os.environ.get('AIPERF_IMAGE_TAG', '0.12.0')}")
    parser.add_argument("--benchmark-build-context", default=str(ROOT / "src/aiperf"),
                        help="Empty string reuses the prebuilt AIPerf image without building")
    parser.add_argument("--job-timeout", type=int, default=3600)
    parser.add_argument("--ready-timeout", type=int, default=300)
    parser.add_argument("--sample-interval", type=float, default=5,
                        help="Seconds between resource samples (plus collection time)")
    parser.add_argument("--reports-dir", type=Path,
                        help="Output root; defaults to docs/reports/<backend>")
    args = parser.parse_args()
    if args.device == "gpu" and os.environ.get("GPU_SHARING", "none") != "none":
        parser.error("This benchmark requires GPU_SHARING=none; use docs/guides/gpu-mps.md for MPS workloads")
    if args.backend not in {"llamacpp", "transformers", "mamba"}:
        parser.error("backend must be llamacpp, transformers or mamba")
    args.reports_dir = args.reports_dir or ROOT / "docs/reports" / ("gpu" if args.device == "gpu" else "") / args.backend
    name = variant_name(args.backend)
    args.image = args.image or f"local/{image_name(args.backend, 'base', args.device)}:0.1.0"
    args.manifests = args.manifests or str(manifests_path(args.backend, "base", args.device))
    args.deployment = args.deployment or name
    args.api_url = args.api_url or f"http://{name}:8000"
    args.model = args.model or {"transformers": "HuggingFaceTB/SmolLM2-135M-Instruct",
                               "mamba": "state-spaces/mamba-130m-hf",
                               "llamacpp": "Qwen/Qwen2.5-0.5B-Instruct"}[args.backend]
    if args.cache_policy not in CACHE_POLICIES:
        parser.error(f"cache policy must be one of {', '.join(CACHE_POLICIES)}")
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
    args.benchmark_build_context = Path(args.benchmark_build_context).resolve() if args.benchmark_build_context else None
    if args.build_target is None and args.build_context == ROOT / "src":
        args.build_target = image_name(args.backend, "base", args.device)
    if args.build_context and not (args.build_context / "Dockerfile").is_file():
        parser.error("build context must contain a Dockerfile")
    if args.benchmark_build_context and not (args.benchmark_build_context / "Dockerfile").is_file():
        parser.error("benchmark build context must contain a Dockerfile")
    args.manifests = Path(args.manifests).resolve()
    if not args.manifests.exists():
        parser.error("inference manifests do not exist")
    return args


def benchmark_manifests(backend):
    profile = {"transformers": "aiperf", "mamba": "aiperf-mamba", "llamacpp": "aiperf-qwen2.5"}[backend]
    return render(ROOT / "k8s" / profile)


def benchmark_template(backend):
    return next(item for item in benchmark_manifests(backend)["items"] if item["kind"] == "Job")


def prepare_model(backend):
    if backend == "mamba":
        run(ROOT / "scripts/download-transformers-model.sh", "mamba-130m")
    elif backend == "transformers":
        run(ROOT / "scripts/download-transformers-model.sh")
    else:
        run(ROOT / "scripts/download-model-llamacpp.sh")
        run(ROOT / "scripts/download-tokenizer-llamacpp.sh")


def resolve_nodes(inference_node, benchmark_node, nodes, device="cpu"):
    items = nodes["items"]
    if device == "gpu" and (not inference_node or not benchmark_node):
        gpu_nodes = [node for node in items if int(node.get("status", {}).get("allocatable", {}).get("nvidia.com/gpu", 0)) >= 1]
        controls = [node for node in items if "node-role.kubernetes.io/control-plane" in node["metadata"].get("labels", {})]
        if len(gpu_nodes) != 1 or len(controls) != 1:
            raise RuntimeError("Default GPU benchmark requires one GPU worker and one control-plane node")
        inference_node = inference_node or gpu_nodes[0]["metadata"]["name"]
        benchmark_node = benchmark_node or controls[0]["metadata"]["name"]
    elif not inference_node or not benchmark_node:
        if len(items) != 1 or "node-role.kubernetes.io/control-plane" not in items[0]["metadata"].get("labels", {}):
            raise RuntimeError("Default benchmark requires one control-plane node. Existing clusters are reused unchanged; "
                               "use the default kind configuration or explicitly set both --inference-node and --benchmark-node.")
        name = items[0]["metadata"]["name"]
        inference_node = inference_node or name
        benchmark_node = benchmark_node or name
    by_name = {node["metadata"]["name"]: node for node in items}
    for name in (inference_node, benchmark_node):
        if name not in by_name:
            raise RuntimeError(f"Requested node does not exist: {name}")
        if not any(condition["type"] == "Ready" and condition["status"] == "True"
                   for condition in by_name[name].get("status", {}).get("conditions", [])):
            raise RuntimeError(f"Requested node is not Ready: {name}")
    if device == "gpu" and int(by_name[inference_node].get("status", {}).get("allocatable", {}).get("nvidia.com/gpu", 0)) < 1:
        raise RuntimeError("Inference node has no allocatable NVIDIA GPU")
    return inference_node, benchmark_node


def stop_other_gpu_engine(deployment_name, timeout):
    for name in ("transformers-base", "transformers-mamba-base", "base-llamacpp"):
        if name == deployment_name:
            continue
        response = kube("get", "deployment", name, "-o", "json", capture=True, check=False)
        if response.returncode:
            continue
        deployment = json.loads(response.stdout)
        kube("scale", f"deployment/{name}", "--replicas=0")
        deadline = time.monotonic() + timeout
        while deployment_pods(deployment):
            if time.monotonic() >= deadline:
                raise RuntimeError(f"GPU deployment {name} did not stop")
            time.sleep(1)


def main():
    args = parse_args()
    os.environ["LOCAL_K8S_SCRIPT"] = str(ROOT / "scripts" / ("local-k8s-gpu.sh" if args.device == "gpu" else "local-k8s.sh"))
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
                "backend": args.backend, "device": args.device,
                "concurrencies": args.concurrencies, "sample_interval_seconds": args.sample_interval,
                "cache_policy": args.cache_policy,
                "inference_node": args.inference_node, "benchmark_node": args.benchmark_node,
                "conditions": []}
    rows = []
    job_name = None
    case_dir = None
    results_reader = None
    print(f"Reports: {report}", flush=True)
    try:
        prepare_model(args.backend)
        run(cluster_script(), "up")
        active = kube_json("get", "jobs", "-l", "benchmark=aiperf-cpu")["items"]
        if any(item.get("status", {}).get("active", 0) for item in active):
            raise RuntimeError("An AIPerf Job is already active; wait for it before restarting the server.")
        nodes = kube_json("get", "nodes")
        args.inference_node, args.benchmark_node = resolve_nodes(
            args.inference_node, args.benchmark_node, nodes, args.device)
        metadata.update(inference_node=args.inference_node, benchmark_node=args.benchmark_node)
        write_json(report / "nodes.json", nodes)
        if args.device == "gpu":
            metadata["inference"] = ensure_image(args.image, args.build_context, args.build_target,
                                                 load_nodes=[args.inference_node])
            metadata["benchmark"] = ensure_image(args.benchmark_image, args.benchmark_build_context,
                                                 load_nodes=[args.benchmark_node])
        else:
            metadata["inference"] = ensure_image(args.image, args.build_context, args.build_target)
            metadata["benchmark"] = ensure_image(args.benchmark_image, args.benchmark_build_context)
        manifests = render(args.manifests)
        items = manifests.get("items", [manifests])
        deployment = next(item for item in items if item["kind"] == "Deployment"
                          and item["metadata"]["name"] == args.deployment)
        if deployment["spec"].get("replicas", 1) != 1:
            raise RuntimeError("Benchmark requires one inference replica.")
        container = next(item for item in deployment["spec"]["template"]["spec"]["containers"]
                         if item["name"] == args.container)
        container["image"] = args.image
        arguments = container.get("args", [])
        if args.backend in {"transformers", "mamba"}:
            metadata["compute_setting"] = "dtype=" + arguments[arguments.index("--dtype") + 1]
            if args.device == "gpu" and arguments[arguments.index("--device") + 1] != "cuda":
                raise RuntimeError("GPU Transformers deployment must select CUDA")
        else:
            layers = arguments[arguments.index("--n-gpu-layers") + 1] if "--n-gpu-layers" in arguments else "0"
            metadata["compute_setting"] = "n_gpu_layers=" + layers
            if args.device == "gpu" and layers == "0":
                raise RuntimeError("GPU llama.cpp deployment must offload layers")
        if args.device == "gpu":
            resources = container["resources"]
            if any(str(resources[level].get("nvidia.com/gpu")) != "1" for level in ("requests", "limits")):
                raise RuntimeError("GPU inference container must request and limit one GPU")
            if deployment["spec"]["template"]["spec"].get("runtimeClassName") != "nvidia":
                raise RuntimeError("GPU inference Pod must use the NVIDIA runtime class")
        if args.inference_node:
            deployment["spec"]["template"]["spec"].setdefault("nodeSelector", {})[
                "kubernetes.io/hostname"] = args.inference_node
        cache = cache_volume(deployment, container) if args.cache_policy != "preserve" else None
        path = report / "inference.json"
        write_json(path, manifests)
        if args.device == "gpu":
            stop_other_gpu_engine(args.deployment, args.ready_timeout)
        kube("apply", "-f", path)
        kube("rollout", "status", f"deployment/{args.deployment}", f"--timeout={args.ready_timeout}s")
        profile = benchmark_manifests(args.backend)
        template = next(item for item in profile["items"] if item["kind"] == "Job")
        resources = {"apiVersion": "v1", "kind": "List", "items": [
            item for item in profile["items"] if item["kind"] != "Job"]}
        if args.device == "gpu":
            for item in resources["items"]:
                if item["kind"] == "Pod":
                    item["spec"].setdefault("nodeSelector", {})["kubernetes.io/hostname"] = args.benchmark_node
                    item["spec"].setdefault("tolerations", []).append(CONTROL_PLANE_TOLERATION)
        results_reader = next(item["metadata"]["name"] for item in resources["items"] if item["kind"] == "Pod")
        write_json(report / "benchmark-resources.json", resources)
        kube("apply", "-f", report / "benchmark-resources.json")
        kube("wait", "--for=condition=Ready", f"pod/{results_reader}", f"--timeout={args.ready_timeout}s")
        if args.benchmark_node:
            template["spec"]["template"]["spec"].setdefault("nodeSelector", {})[
                "kubernetes.io/hostname"] = args.benchmark_node
        if args.device == "gpu":
            template["spec"]["template"]["spec"].setdefault("tolerations", []).append(CONTROL_PLANE_TOLERATION)
        for condition_index, concurrency in enumerate(args.concurrencies):
            case_dir = report / f"c{concurrency}"
            case_dir.mkdir()
            before = {pod["metadata"]["uid"] for pod in deployment_pods(deployment)}
            condition = {"concurrency": concurrency, "status": "running"}
            metadata["conditions"].append(condition)
            save_summary(report, metadata, rows)
            if clears_cache(args.cache_policy, condition_index):
                print(f"Clearing PVC {cache['pvc']} before concurrency={concurrency}", flush=True)
                condition["cache_clear"] = clear_pvc_cache(
                    deployment, container, cache, f"{run_id}-clear-c{concurrency}", case_dir, args.ready_timeout)
            else:
                print(f"Restarting {args.deployment} before concurrency={concurrency}", flush=True)
                kube("rollout", "restart", f"deployment/{args.deployment}")
            kube("rollout", "status", f"deployment/{args.deployment}", f"--timeout={args.ready_timeout}s")
            pods = [pod for pod in deployment_pods(deployment) if not pod["metadata"].get("deletionTimestamp")]
            if len(pods) != 1 or pods[0]["metadata"]["uid"] in before:
                raise RuntimeError("Expected exactly one newly restarted inference Pod.")
            write_json(case_dir / "inference-pod.json", pods[0])
            condition.update(pod_uid=pods[0]["metadata"]["uid"], pod_name=pods[0]["metadata"]["name"])
            if args.device == "gpu":
                kube("exec", pods[0]["metadata"]["name"], "--", "nvidia-smi", "-L", capture=True)
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
            gpu_sampler = GPUSampler(case_dir) if args.device == "gpu" else None
            sampler.sample()
            if gpu_sampler:
                gpu_sampler.sample()
            condition["started_at"] = datetime.now(timezone.utc).isoformat()
            save_summary(report, metadata, rows)
            kube("create", "-f", case_dir / "job.json")
            print(f"Measuring concurrency={concurrency}: {job_name}", flush=True)
            wait_job(job_name, args.job_timeout, sampler, args.sample_interval, gpu_sampler)
            current = next(pod for pod in deployment_pods(deployment)
                           if pod["metadata"]["uid"] == condition["pod_uid"])
            write_json(case_dir / "inference-pod.json", current)
            if any(item["restartCount"] for item in current.get("status", {}).get("containerStatuses", [])):
                raise RuntimeError("Inference container restarted during measurement")
            clients = kube_json("get", "pods", "-l", f"job-name={job_name}")
            write_json(case_dir / "aiperf-pods.json", clients)
            if any(status["restartCount"] for pod in clients["items"]
                   for status in pod.get("status", {}).get("containerStatuses", [])):
                raise RuntimeError("AIPerf container restarted during measurement")
            (case_dir / "aiperf.log").write_text(kube("logs", f"job/{job_name}", capture=True).stdout)
            kube("cp", f"{results_reader}:{artifact_path}/.", case_dir / "artifacts")
            result = case_dir / "artifacts/profile_export_aiperf.json"
            export_requests(result.parent / "profile_export.jsonl", case_dir / "requests.csv")
            condition["resource_collection"] = sampler.validate()
            row = collect_summary(result, concurrency)
            if gpu_sampler:
                gpu = gpu_sampler.summary()
                condition["gpu_collection"] = gpu
                row.update(gpu)
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
                kube("cp", f"{results_reader}:/results/{run_id}/{case_dir.name}/.",
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
