#!/usr/bin/env python3
"""Repeat all inference variants with fixed images and node placement."""

import argparse
import csv
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("benchmark", ROOT / "scripts/run-benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)
CONDITIONS = (
    ("base", "base", "preserve"),
    ("enhanced-batch", "enhanced-batch", "preserve"),
    ("enhanced-cache-clear", "enhanced-cache", "clear-per-concurrency"),
    ("enhanced-cache-preserve", "enhanced-cache", "clear-before-sweep"),
)
TRANSFORMERS_CONDITIONS = (
    ("base", "base", "preserve"),
    ("enhanced-batch", "enhanced-batch", "preserve"),
    ("enhanced-cache", "enhanced-cache", "clear-before-sweep"),
)


def conditions_for(backend):
    return TRANSFORMERS_CONDITIONS if backend == "transformers" else CONDITIONS


def backend_for(metadata):
    return benchmark.normalize_backend(metadata.get("backend", "llamacpp"))


def inference_image(metadata, variant):
    backend = backend_for(metadata)
    image = f"local/{benchmark.variant_name(backend, variant)}:{metadata['image_tag']}"
    legacy = f"local/llama-{variant}:{metadata['image_tag']}"
    # Archived suites retain their measured image references when resumed.
    return legacy if backend == "llamacpp" and legacy in metadata.get("images", {}) else image


def plan(repetitions, backend="transformers"):
    cases = []
    conditions = conditions_for(backend)
    for repetition in range(1, repetitions + 1):
        offset = (repetition - 1) % len(conditions)
        for label, variant, policy in conditions[offset:] + conditions[:offset]:
            cases.append({"repetition": repetition, "condition": label, "variant": variant,
                          "cache_policy": policy, "status": "pending",
                          "directory": f"r{repetition}/{label}"})
    return cases


def aggregate(rows):
    output = []
    metrics = [key for key in rows[0] if key not in {"repetition", "condition", "concurrency", "report"}]
    for label in dict.fromkeys(row["condition"] for row in rows):
        for concurrency in (1, 2, 4, 8):
            group = [row for row in rows if row["condition"] == label and row["concurrency"] == concurrency]
            if not group:
                continue
            result = {"condition": label, "concurrency": concurrency, "repetitions": len(group)}
            for metric in metrics:
                values = [row[metric] for row in group if row[metric] is not None]
                if len(values) != len(group):
                    raise RuntimeError(f"Incomplete metric {metric} for {label}/c{concurrency}")
                result.update({f"{metric}_mean": statistics.mean(values),
                               f"{metric}_std": statistics.stdev(values) if len(values) > 1 else None,
                               f"{metric}_min": min(values), f"{metric}_max": max(values)})
            output.append(result)
    return output


def case_command(case, metadata, destination):
    backend = backend_for(metadata)
    name = benchmark.variant_name(backend)
    return [sys.executable, str(ROOT / "scripts/run-benchmark.py"),
            "--backend", backend,
            "--image", inference_image(metadata, case["variant"]),
            "--build-context", "", "--manifests", str(ROOT / "k8s" / benchmark.variant_name(backend, case["variant"])),
            "--deployment", name, "--container", "api", "--api-url", f"http://{name}:8000",
            "--concurrencies", "1,2,4,8", "--cache-policy", case["cache_policy"],
            "--benchmark-image", metadata["benchmark_image"],
            "--benchmark-build-context", "",
            "--inference-node", metadata["inference_node"], "--benchmark-node", metadata["benchmark_node"],
            "--reports-dir", str(destination)]


def read_case(report, case, metadata):
    run = json.loads((report / "run.json").read_text())
    if run["status"] != "complete" or run["concurrencies"] != [1, 2, 4, 8]:
        raise RuntimeError(f"Incomplete sweep: {report}")
    if run["cache_policy"] != case["cache_policy"]:
        raise RuntimeError(f"Unexpected cache policy: {report}")
    backend = backend_for(metadata)
    if backend_for(run) != backend:
        raise RuntimeError(f"Unexpected backend: {report}")
    for role, image in (("inference", inference_image(metadata, case["variant"])),
                        ("benchmark", metadata["benchmark_image"])):
        if run[role]["id"] != metadata["images"][image]["id"]:
            raise RuntimeError(f"Image changed during the suite: {image}")
    if len(run["conditions"]) != 4 or len({c["pod_uid"] for c in run["conditions"]}) != 4:
        raise RuntimeError(f"Expected four distinct inference Pods: {report}")
    for index, condition in enumerate(run["conditions"]):
        if condition["status"] != "complete" or condition["output_length_check"]["shortfalls"]:
            raise RuntimeError(f"Invalid condition: {report}")
        clear = condition.get("cache_clear")
        if bool(clear) != benchmark.clears_cache(case["cache_policy"], index):
            raise RuntimeError(f"Unexpected cache cleanup schedule: {report}")
        if clear and clear["remaining_entries"] != 0:
            raise RuntimeError(f"Nonempty cache before measurement: {report}")
        directory = report / f"c{condition['concurrency']}"
        inference = json.loads((directory / "inference-pod.json").read_text())
        clients = json.loads((directory / "aiperf-pods.json").read_text())["items"]
        for pod, node in [(inference, metadata["inference_node"]),
                          *[(client, metadata["benchmark_node"]) for client in clients]]:
            if pod["spec"]["nodeName"] != node or pod["status"]["qosClass"] != "Guaranteed":
                raise RuntimeError(f"Unexpected node or QoS: {report}")
            if any(s["restartCount"] for s in pod["status"].get("containerStatuses", [])):
                raise RuntimeError(f"Container restarted: {report}")
    rows = [json.loads(line) for line in (report / "summary.jsonl").read_text().splitlines()]
    if len(rows) != 4 or any(row["requests"] != 100 for row in rows):
        raise RuntimeError(f"Unexpected request count: {report}")
    for row, condition in zip(rows, run["conditions"], strict=True):
        if row["concurrency"] != condition["concurrency"]:
            raise RuntimeError(f"Unexpected concurrency order: {report}")
        raw = json.loads((report / f"c{row['concurrency']}/artifacts/profile_export_aiperf.json").read_text())
        row["profiling_seconds"] = benchmark.metric(raw, "benchmark_duration")
        row["job_and_collection_seconds"] = (
            datetime.fromisoformat(condition["completed_at"]) - datetime.fromisoformat(condition["started_at"])
        ).total_seconds()
    case["elapsed_seconds"] = (datetime.fromisoformat(run["finished_at"]) -
                               datetime.fromisoformat(run["started_at"])).total_seconds()
    case["profiling_seconds"] = sum(row["profiling_seconds"] for row in rows)
    return [{"repetition": case["repetition"], "condition": case["condition"],
             "report": case["report"], **row} for row in rows]


def save_suite(directory, metadata, rows):
    benchmark.write_json(directory / "run.json", metadata)
    if not rows:
        return
    for filename, records in (("runs.csv", rows), ("summary.csv", aggregate(rows))):
        with (directory / filename).open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    (directory / "summary.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    lines = ["# Inference benchmark: repeated sweeps", "",
             f"- Status: {metadata['status']}", f"- Repetitions per condition: {metadata['repetitions']}",
             f"- Backend: `{backend_for(metadata)}`",
             f"- Inference node: `{metadata['inference_node']}`; AIPerf node: `{metadata['benchmark_node']}`",
             "- Each sweep uses concurrency 1, 2, 4, 8; each step has 2 warmup and 100 profiling requests.",
             "- Each step starts with a fresh inference Pod. Image IDs and node placement are fixed across repetitions.",
             ("- Cache: empty PVC before each sweep, then retain it between steps."
              if metadata.get("backend") == "transformers" else
              "- Cache clear: empty PVC before every step. Cache preserve: empty PVC before the sweep, then retain it between steps."),
             "- Cache clearing precedes warmup; cache can fill and be reused within each step.",
             "- Execution order rotates by one condition each repetition. All sweeps run sequentially.",
             "- Values are mean ± sample standard deviation across sweeps. TTFT p95 is the mean of per-sweep p95 values, not a pooled p95.", "",
             "| Condition | Concurrency | Runs | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | Profiling (s) |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in aggregate(rows):
        cells = [row["condition"], str(row["concurrency"]), str(row["repetitions"])]
        for metric in ("output_tokens_per_second", "ttft_avg_ms", "ttft_p95_ms", "itl_avg_ms", "profiling_seconds"):
            std = row[f"{metric}_std"]
            cells.append(f"{row[f'{metric}_mean']:.2f}" + (f" ± {std:.2f}" if std is not None else ""))
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "Profiling excludes warmup, Pod preparation and result collection. Sweep elapsed time includes these tasks.",
              "", "## Sweep reports", "", "| Order | Repetition | Condition | Status | Elapsed (s) | Report |",
              "| ---: | ---: | --- | --- | ---: | --- |"]
    for index, case in enumerate(metadata["cases"], 1):
        link = f"[summary]({case['report']}/summary.md)" if case.get("report") else ""
        elapsed = f"{case['elapsed_seconds']:.2f}" if "elapsed_seconds" in case else ""
        lines.append(f"| {index} | {case['repetition']} | {case['condition']} | {case['status']} | {elapsed} | {link} |")
    lines += ["", "`runs.csv` and `summary.jsonl` contain the individual sweep metrics; `summary.csv` includes mean, standard deviation, minimum, and maximum for every metric.",
              "Image IDs, commands, and execution order are recorded in `run.json`. Per-request exports and resource time series are saved locally under each sweep report and are excluded from Git."]
    (directory / "summary.md").write_text("\n".join(lines) + "\n")


def prepare_images(metadata, build):
    backend = backend_for(metadata)
    images = [(inference_image(metadata, variant), ROOT / "src", benchmark.variant_name(backend, variant))
              for variant in dict.fromkeys(variant for _, variant, _ in conditions_for(backend))]
    images.append((metadata["benchmark_image"], ROOT / "src/aiperf", None))
    for image, context, target in images:
        # An interrupted suite must retain already recorded image IDs.
        rebuild = build and image not in metadata["images"]
        info = benchmark.ensure_image(image, context if rebuild else None, target if rebuild else None)
        if image in metadata["images"] and info["id"] != metadata["images"][image]["id"]:
            raise RuntimeError(f"Image changed since suite started: {image}")
        metadata["images"].setdefault(image, info)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("llamacpp", "transformers"), type=benchmark.normalize_backend,
                        default=os.environ.get("INFERENCE_BACKEND", "transformers"))
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--inference-node", help="Default: the single control-plane node")
    parser.add_argument("--benchmark-node", help="Default: the same single control-plane node")
    parser.add_argument("--image-tag", default="0.1.0")
    parser.add_argument("--benchmark-image", default="local/aiperf:0.12.0")
    parser.add_argument("--reports-dir", type=Path, help="Output root; defaults to docs/reports/<backend>")
    parser.add_argument("--resume", type=Path, help="Resume a suite, retaining its completed sweeps and settings")
    parser.add_argument("--skip-build", action="store_true", help="Load existing local images without rebuilding")
    parser.add_argument("--prepare-only", action="store_true", help="Prepare cluster, model and images without running measurements")
    args = parser.parse_args()
    if args.repetitions < 1:
        parser.error("repetitions must be positive")
    if args.backend not in {"llamacpp", "transformers"}:
        parser.error("backend must be llamacpp or transformers")
    args.reports_dir = args.reports_dir or ROOT / "docs/reports" / args.backend
    return args


def main():
    args = parse_args()
    state = Path(os.environ.get("LOCAL_K8S_STATE_DIR", ROOT / ".local-k8s"))
    state.mkdir(parents=True, exist_ok=True)
    with (state / "benchmark-suite.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        started = datetime.now(timezone.utc)
        directory = args.resume.resolve() if args.resume else args.reports_dir.resolve() / (
            "benchmark-suite-" + started.strftime("%Y%m%d-%H%M%S-%f"))
        directory.mkdir(parents=True, exist_ok=bool(args.resume))
        if args.resume:
            metadata = json.loads((directory / "run.json").read_text())
        else:
            metadata = {"started_at": started.isoformat(), "status": "preparing", "backend": args.backend,
                        "repetitions": args.repetitions, "image_tag": args.image_tag,
                        "benchmark_image": args.benchmark_image, "inference_node": args.inference_node,
                        "benchmark_node": args.benchmark_node, "images": {}, "cases": plan(args.repetitions, args.backend)}
        rows = []
        print(f"Suite: {directory}", flush=True)
        try:
            benchmark.run(ROOT / "scripts/local-k8s.sh", "up")
            backend = backend_for(metadata)
            nodes = benchmark.kube_json("get", "nodes")
            metadata["inference_node"], metadata["benchmark_node"] = benchmark.resolve_nodes(
                metadata["inference_node"], metadata["benchmark_node"], nodes)
            benchmark.write_json(directory / "nodes.json", nodes)
            active = benchmark.kube_json("get", "jobs", "-l", "benchmark=aiperf-cpu")["items"]
            if any(item.get("status", {}).get("active", 0) for item in active):
                raise RuntimeError("An AIPerf Job is already active; wait for it before preparing images.")
            benchmark.prepare_model(backend)
            prepare_images(metadata, build=not args.skip_build)
            metadata["prepared_at"] = datetime.now(timezone.utc).isoformat()
            if args.prepare_only:
                metadata["status"] = "prepared"
                print(f"Prepared suite without measurements: {directory / 'run.json'}", flush=True)
                return 0
            metadata.setdefault("measurement_started_at", datetime.now(timezone.utc).isoformat())
            metadata["status"] = "running"
            metadata.pop("error", None)
            for index, case in enumerate(metadata["cases"], 1):
                if case["status"] == "complete":
                    rows.extend(read_case(directory / case["report"], case, metadata))
                    continue
                destination = directory / case["directory"]
                destination.mkdir(parents=True, exist_ok=True)
                before = set(destination.glob("bench-*/run.json"))
                command = case_command(case, metadata, destination)
                case.update(status="running", command=command, started_at=datetime.now(timezone.utc).isoformat())
                save_suite(directory, metadata, rows)
                print(f"START {index}/{len(metadata['cases'])}: repetition={case['repetition']} {case['condition']}", flush=True)
                with (destination / "runner.log").open("a") as log:
                    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
                reports = set(destination.glob("bench-*/run.json")) - before
                if len(reports) != 1:
                    raise RuntimeError(f"Expected one new sweep report: {destination}")
                report = reports.pop().parent
                case["report"] = str(report.relative_to(directory))
                if result.returncode:
                    raise RuntimeError(f"Sweep failed; inspect {destination / 'runner.log'}")
                rows.extend(read_case(report, case, metadata))
                case.update(status="complete", finished_at=datetime.now(timezone.utc).isoformat())
                save_suite(directory, metadata, rows)
                print(f"DONE {index}/{len(metadata['cases'])}: {case['condition']}", flush=True)
            metadata["status"] = "complete"
        except (Exception, KeyboardInterrupt) as exc:
            metadata.update(status="failed", error=str(exc) or "Interrupted")
            for case in metadata["cases"]:
                if case["status"] == "running":
                    case["status"] = "failed"
            print(f"Suite failed: {exc}", file=sys.stderr, flush=True)
            return 1
        finally:
            metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
            save_suite(directory, metadata, rows)
        print(f"Completed suite: {directory / 'summary.md'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
