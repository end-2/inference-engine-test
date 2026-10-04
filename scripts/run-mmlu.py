#!/usr/bin/env python3
"""Build the evaluator image, run MMLU in a Kubernetes Job, and collect reports."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mmlu = load_script("check-mmlu")
benchmark = load_script("run-benchmark")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cpu", "gpu"), default="cpu")
    parser.add_argument("--namespace", default="default", help="Existing namespace for the Job and server")
    parser.add_argument("--node", help="Evaluation node; defaults to a control-plane node")
    parser.add_argument("--image", default="local/mmlu:0.1.0")
    parser.add_argument("--job-timeout", type=int, default=14400)
    parser.add_argument("--ready-timeout", type=int, default=300)
    parser.add_argument("--keep-resources", action="store_true", help="Keep Job, reader Pod and PVC after collection")
    args = mmlu.parse_args(argv, parser=parser, default_url="")
    args.url = args.url or f"http://{mmlu.CATALOG[args.backend]['deployment']}:8000"
    if min(args.job_timeout, args.ready_timeout) < 1:
        parser.error("--job-timeout and --ready-timeout must be positive")
    return args


def evaluator_args(args):
    command = ["--backend", args.backend, "--url", args.url, "--model", args.model,
               "--data-dir", "/work/data", "--output", "/work/results/summary.json",
               "--few-shot", str(args.few_shot), "--seed", str(args.seed),
               "--max-tokens", str(args.max_tokens), "--timeout", str(args.timeout)]
    for name, value in (("--limit", args.limit), ("--min-accuracy", args.min_accuracy)):
        if value is not None:
            command.extend([name, str(value)])
    if args.subjects:
        command.extend(["--subjects", *args.subjects])
    return command


def prepare_image(image, node, device="cpu"):
    # A small build context ensures image caching tracks only evaluator inputs.
    with tempfile.TemporaryDirectory(prefix="mmlu-image-") as directory:
        context = Path(directory)
        for source, target in ((ROOT / "benchmarks/mmlu/Dockerfile", "Dockerfile"),
                               (ROOT / "scripts/check-mmlu.py", "scripts/check-mmlu.py"),
                               (ROOT / "benchmarks/inference.json", "benchmarks/inference.json")):
            destination = context / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        return benchmark.ensure_image(image, context, load_nodes=[node] if device == "gpu" else None)


def main(argv=None):
    args = parse_args(argv)
    os.environ["LOCAL_K8S_SCRIPT"] = str(ROOT / "scripts" / (
        "local-k8s-gpu.sh" if args.device == "gpu" else "local-k8s.sh"))

    def kube(*command, **kwargs):
        return benchmark.kube("--namespace", args.namespace, *command, **kwargs)

    if args.download_data and not args.data_dir.exists():
        print(f"Downloading MMLU from {mmlu.DATA_URL}", flush=True)
        mmlu.download_data(args.data_dir, args.timeout)
    _, hashes = mmlu.load_dataset(args)
    nodes = benchmark.kube_json("get", "nodes")["items"]
    available = {node["metadata"]["name"]: node for node in nodes}
    if not available:
        raise ValueError("No Kubernetes nodes found; prepare the cluster and inference server first")
    node = args.node or next((name for name, item in available.items()
                             if "node-role.kubernetes.io/control-plane" in item["metadata"].get("labels", {})),
                            sorted(available)[0])
    if node not in available:
        raise ValueError(f"Unknown evaluation node: {node}")
    hostname = available[node]["metadata"]["labels"]["kubernetes.io/hostname"]
    run_id = "mmlu-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    output = (args.output or ROOT / "reports" / ("gpu" if args.device == "gpu" else "")
              / args.backend / run_id / "summary.json").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    diagnostics = output.parent / f"{output.stem}-run"
    diagnostics.mkdir(exist_ok=True)
    reader = f"{run_id}-reader"
    metadata = {"run_id": run_id, "namespace": args.namespace, "node": node,
                "device": args.device, "url": args.url, "model": args.model,
                "status": "preparing", "dataset_file_sha256": hashes}
    created = False
    collected = False
    exit_code = 1
    values = {"name": run_id, "image": args.image, "node": hostname,
              "job": {"enabled": False, "activeDeadlineSeconds": args.job_timeout},
              "args": evaluator_args(args)}

    def apply_resources():
        benchmark.write_json(diagnostics / "values.json", values)
        manifest = benchmark.run(ROOT / "scripts/render-k8s.sh", ROOT / "k8s/mmlu",
                                 "-f", diagnostics / "values.json", capture=True).stdout
        path = diagnostics / "workloads.yaml"
        path.write_text(manifest)
        kube("apply", "-f", path)

    print(f"MMLU Job: {run_id}, report: {output}", flush=True)
    try:
        metadata["image"] = prepare_image(args.image, node, args.device)
        created = True
        apply_resources()
        kube("wait", "--for=condition=Ready", f"pod/{reader}", f"--timeout={args.ready_timeout}s")
        kube("exec", reader, "--", "mkdir", "-p", "/work/data", "/work/results")
        # Transfer only the selected subjects and required splits to the evaluation PVC.
        with tempfile.TemporaryDirectory(prefix="mmlu-data-") as directory:
            staging = Path(directory)
            for relative in hashes:
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(args.data_dir / relative, destination)
            kube("cp", f"{staging}/.", f"{reader}:/work/data")
        values["job"]["enabled"] = True
        apply_resources()
        metadata["status"] = "running"
        benchmark.wait_job(run_id, args.job_timeout, namespace=args.namespace)
        exit_code = 0
    except (RuntimeError, OSError, ValueError, KeyboardInterrupt) as error:
        metadata["error"] = str(error) or "Interrupted"
        exit_code = 130 if isinstance(error, KeyboardInterrupt) else 1
        print(f"MMLU Job stopped: {metadata['error']}", file=sys.stderr)
    finally:
        if created:
            for command, filename in ((("logs", f"job/{run_id}"), "mmlu.log"),
                                      (("get", "pods", "-l", f"mmlu-run={run_id}", "-o", "json"), "pods.json"),
                                      (("describe", "job", run_id), "job.txt")):
                result = kube(*command, capture=True, check=False)
                (diagnostics / filename).write_text((result.stdout or "") + (result.stderr or ""))
            if exit_code and (not args.keep_resources or exit_code == 130):
                kube("delete", "job", run_id, "--ignore-not-found=true", "--wait=true",
                     "--timeout=60s", check=False)
            with tempfile.TemporaryDirectory(prefix="mmlu-results-") as directory:
                result = kube("cp", f"{reader}:/work/results/.", directory, check=False)
                if result.returncode == 0:
                    for source_name, destination in (("summary.jsonl", output.with_suffix(".jsonl")),
                                                      ("summary.json", output)):
                        source = Path(directory) / source_name
                        if source.is_file():
                            shutil.copy2(source, destination)
                    summary = Path(directory) / "summary.json"
                    if summary.is_file():
                        report = json.loads(summary.read_text())
                        collected = bool(report.get("complete"))
                        exit_code = exit_code or (0 if report.get("passed") else 1)
                        print(f"Accuracy: {report['summary']['accuracy']}, report: {output}")
                if not collected:
                    exit_code = exit_code or 1
            if collected and not args.keep_resources:
                kube("delete", "job,pod,pvc", "-l", f"mmlu-run={run_id}",
                     "--ignore-not-found=true", "--wait=true", "--timeout=60s")
            else:
                print(f"Resources retained in namespace {args.namespace}: mmlu-run={run_id}")
        metadata.update(status="completed" if exit_code == 0 else "failed",
                        collected=collected, exit_code=exit_code,
                        finished_at=datetime.now(timezone.utc).isoformat())
        benchmark.write_json(diagnostics / "run.json", metadata)
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, mmlu.csv.Error, mmlu.tarfile.TarError,
            mmlu.http.client.HTTPException) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
