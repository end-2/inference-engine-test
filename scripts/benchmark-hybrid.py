#!/usr/bin/env python3
"""Compare serial Jamba generation with batching and controlled HiCache tiers."""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gc
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
CONDITIONS = ("base", "batch", "cold", "gpu", "ram", "disk")
METRICS = ("output_tokens_per_second", "latency_ms", "ttft_ms", "peak_allocated_mib", "peak_reserved_mib")


def positive_list(value):
    values = [int(part) for part in value.split(",")]
    if not values or min(values) < 1 or len(values) != len(set(values)):
        raise argparse.ArgumentTypeError("Expected distinct positive integers")
    return values


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


class Recorder:
    def __init__(self):
        self.tokens, self.pieces = [], []
        self.first_token = None

    def __call__(self, text):
        self.pieces.append(text)

    def observe(self, tokens):
        if self.first_token is None:
            self.first_token = time.perf_counter()
        self.tokens.extend(tokens.reshape(-1).tolist())


def observe_tokens(backend):
    original = backend._streamer

    def streamer(emit, skip_prompt=False):
        delegate = original(emit, skip_prompt=skip_prompt)

        class Observed:
            skip = skip_prompt

            def put(self, value):
                if self.skip:
                    self.skip = False
                else:
                    emit.observe(value)
                delegate.put(value)

            def end(self):
                delegate.end()

        return Observed()

    backend._streamer = streamer


def clear_cache(cache):
    for key in list(cache.gpu) + list(cache.ram) + list(cache.disk.disk):
        cache.discard(key)


def arrange_tier(backend, prompts, condition, budgets):
    from inference.contracts import Generation

    cache = backend.cache
    if condition == "batch":
        return
    if condition == "cold":
        clear_cache(cache)
        return
    cache.gpu_limit, cache.ram_limit = budgets
    clear_cache(cache)
    backend.generate_batch([Generation(prompt, 1, 0, 1, True, threading.Event()) for prompt in prompts])
    states = [cache.get(prompt[:-1], backend.settings.cache_min_prefix) for prompt in prompts]
    if any(state is None or len(state.tokens) != len(prompt) - 1 for state, prompt in zip(states, prompts)):
        raise RuntimeError("Warm checkpoints do not fit the configured cache budgets")
    clear_cache(cache)
    cache.gpu_limit = budgets[0] if condition == "gpu" else 0
    cache.ram_limit = 0 if condition == "disk" else budgets[1]
    for state in states:
        cache.put(state)
    expected = cache.disk.disk if condition == "disk" else getattr(cache, condition)
    if any(tuple(prompt[:-1]) not in expected for prompt in prompts):
        raise RuntimeError(f"Failed to prepare the {condition} tier")
    cache.gpu_limit, cache.ram_limit = budgets


def counters(backend):
    cache = getattr(backend, "cache", None)
    if cache is None:
        return {}
    return {**cache.stats, "disk_evictions": cache.disk.stats["evictions"],
            "disk_errors": cache.disk.stats["errors"], "restored_tokens": backend.restored_tokens}


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["condition"], row["prompt_tokens"], row["concurrency"])].append(row)
    summary = []
    for (condition, length, concurrency), group in groups.items():
        result = dict(condition=condition, prompt_tokens=length, concurrency=concurrency,
                      waves=len(group), requests=sum(row["requests"] for row in group))
        for metric in METRICS:
            values = [row[metric] for row in group]
            result[f"{metric}_mean"] = statistics.mean(values)
            result[f"{metric}_std"] = statistics.stdev(values) if len(values) > 1 else 0
        result["restored_tokens"] = sum(row["cache_delta"].get("restored_tokens", 0) for row in group)
        result["latency_p95_ms"] = percentile([value for row in group for value in row["latencies_ms"]], 0.95)
        result["ttft_p95_ms"] = percentile([value for row in group for value in row["ttfts_ms"]], 0.95)
        summary.append(result)
    baselines = {(row["prompt_tokens"], row["concurrency"]): row for row in summary if row["condition"] == "base"}
    for row in summary:
        base = baselines.get((row["prompt_tokens"], row["concurrency"]))
        row["throughput_vs_base"] = row["output_tokens_per_second_mean"] / base["output_tokens_per_second_mean"] if base else None
        row["ttft_reduction_pct"] = (1 - row["ttft_ms_mean"] / base["ttft_ms_mean"]) * 100 if base else None
    return sorted(summary, key=lambda row: (row["prompt_tokens"], row["concurrency"], CONDITIONS.index(row["condition"])))


def save_reports(directory, metadata, rows):
    import csv

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "run.json").write_text(json.dumps(metadata, indent=2) + "\n")
    if not rows:
        return
    summary = summarize(rows)
    with (directory / "runs.csv").open("w") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
                          for key, value in row.items()} for row in rows)
    with (directory / "summary.csv").open("w") as output:
        writer = csv.DictWriter(output, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)
    (directory / "summary.jsonl").write_text("".join(json.dumps(row) + "\n" for row in summary))
    lines = ["# Jamba base 및 hybrid 벤치마크", "",
             f"상태: `{metadata['status']}`. 모델: `{metadata['model_id']}`. GPU: `{metadata['gpu']}`. "
             f"dtype: `{metadata['dtype']}`, Mamba 경로: `{metadata.get('kernel_backend')}`.", "",
             "같은 모델의 기본 `generate()` 직렬 처리와 hybrid 엔진을 비교합니다. "
             "base도 요청 내부의 dynamic KV 및 Mamba cache를 사용합니다.", "",
             f"입력 {metadata['prompt_lengths']}토큰, 출력 {metadata['max_tokens']}토큰, "
             f"동시성 {metadata['concurrencies']}, {metadata['repetitions']}회 반복, "
             f"반복당 {metadata['waves']}개 요청 묶음을 측정했습니다. "
             "요청 묶음마다 동시성 수만큼 서로 다른 입력을 동시에 제출합니다.", "",
             "- base: 단일 작업자의 기본 generate(), 요청 간 캐시 없음.",
             "- batch: hybrid 버퍼와 배치 처리, 모든 prefix 캐시 비활성화.",
             "- cold: 측정 묶음 직전에 캐시 초기화, checkpoint 생성 비용 포함.",
             "- gpu, ram, disk: 각 묶음 전에 해당 계층의 checkpoint 준비, 측정에는 조회 및 승격 비용 포함.", "",
             "| 입력 | 동시성 | 조건 | 요청 수 | 출력 tok/s | base 대비 | 평균 TTFT ms | 평균 지연 ms | p95 지연 ms | GPU 할당 peak MiB |",
             "| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in summary:
        ratio = f"{row['throughput_vs_base']:.2f}x" if row["throughput_vs_base"] is not None else ""
        lines.append(f"| {row['prompt_tokens']} | {row['concurrency']} | {row['condition']} | {row['requests']} | "
                     f"{row['output_tokens_per_second_mean']:.2f} | {ratio} | {row['ttft_ms_mean']:.2f} | "
                     f"{row['latency_ms_mean']:.2f} | {row['latency_p95_ms']:.2f} | {row['peak_allocated_mib_mean']:.1f} |")
    lines += ["", "## 측정 조건", "",
              "HTTP와 토크나이저 처리 시간은 제외하고 엔진의 대기열, 배치 대기, 생성 및 스트리머 비용을 포함합니다. "
              "TTFT는 첫 생성 토큰이 CPU 스트리머에 도착한 시점이며 첫 텍스트 청크 시간과 다릅니다.", "",
              "모델 로딩, 워밍업, 캐시 초기화 및 warm checkpoint 준비는 측정에서 제외합니다. "
              "greedy decoding과 EOS 억제로 출력 길이를 고정합니다. 모든 측정 요청의 토큰 ID와 사용량을 "
              "같은 모델의 base 출력과 대조합니다. GPU 동기화 후 시간을 측정하며, 반복마다 조건 순서를 순환합니다.", "",
              "평균 지표는 요청 묶음별 지표의 평균입니다. p95는 같은 조건의 모든 반복 요청을 합쳐 nearest-rank로 계산하며, "
              "표본 수가 적으므로 서비스 부하의 p95로 해석하지 않습니다. GPU 메모리는 "
              "PyTorch allocator의 peak allocated이며 GPU 전체 사용량이 아닙니다. "
              "표준편차와 reserved 메모리는 summary.csv에 있습니다.", "",
              "disk 조건은 직전에 기록한 파일을 읽으므로 OS page cache의 영향을 포함합니다. "
              "물리 디스크의 cold read 벤치마크가 아닙니다. "
              "Jamba-tiny-dev는 개발용 모델이며 대형 Jamba 배포의 처리량을 나타내지 않습니다.", "",
              "[실행 메타데이터와 검증](run.json), [요약 CSV](summary.csv), [묶음별 원본 지표](runs.csv). "
              "요청별 토큰 및 타이밍은 로컬 requests.jsonl에 보관합니다.", ""]
    (directory / "summary.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-id", default="ai21labs/Jamba-tiny-dev")
    parser.add_argument("--revision", default="ed303361004ac875426a61675edecf8e9d976882")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--dtype", choices=("float32", "float16", "bfloat16"), default="float16")
    parser.add_argument("--prompt-lengths", type=positive_list, default=[64, 256])
    parser.add_argument("--concurrencies", type=positive_list, default=[1, 2, 4, 8])
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--waves", type=int, default=2)
    parser.add_argument("--batch-wait-ms", type=float, default=5)
    parser.add_argument("--conditions", default=",".join(CONDITIONS))
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    conditions = args.conditions.split(",")
    if (not set(conditions) <= set(CONDITIONS) or len(set(conditions)) != len(conditions)
            or min(args.max_tokens, args.repetitions, args.waves) < 1 or min(args.prompt_lengths) < 2):
        parser.error("Invalid conditions, lengths or repetition counts")
    if args.device == "cpu" and "gpu" in conditions:
        parser.error("The GPU cache condition requires --device cuda")
    if args.report_dir.exists() and any(args.report_dir.iterdir()):
        parser.error("report-dir must be empty or absent")

    import torch
    import transformers
    from huggingface.jamba.base.engine import EngineSettings as BaseSettings, TorchEngine as BaseEngine
    from huggingface.jamba.hybrid.engine import EngineSettings, TorchEngine

    def sync():
        if args.device == "cuda":
            torch.cuda.synchronize()

    settings = BaseSettings(args.model, n_ctx=max(args.prompt_lengths) + args.max_tokens,
                            device=args.device, dtype=args.dtype, n_threads=4, mamba_kernels="off")
    metadata = {**vars(args), "model": str(args.model), "report_dir": str(args.report_dir),
                "created_at": datetime.now(timezone.utc).isoformat(), "status": "running",
                "torch": torch.__version__, "transformers": transformers.__version__,
                "gpu": torch.cuda.get_device_name() if args.device == "cuda" else None,
                "conditions": conditions, "verified_requests": 0, "output_mismatches": 0,
                "max_parallel": max(args.concurrencies), "n_ctx": settings.n_ctx, "n_threads": settings.n_threads,
                "cache_budgets_mib": {"gpu": 64 if args.device == "cuda" else 0, "ram": 256, "disk": 1024},
                "disk_page_cache": "not dropped; warm checkpoint files",
                "command": sys.argv, "source_sha256": {}, "model_sha256": {}}
    for category, paths in (("source_sha256", [Path(__file__), *sorted((ROOT / "src/huggingface").rglob("*.py")),
                                              *sorted((ROOT / "src/inference").glob("*.py"))]),
                            ("model_sha256", sorted(args.model.glob("*")))):
        for path in paths:
            if path.is_file():
                with path.open("rb") as source:
                    key = str(path.relative_to(ROOT)) if category == "source_sha256" else path.name
                    metadata[category][key] = hashlib.file_digest(source, "sha256").hexdigest()
    rows, prompts, expected = [], {}, {}
    save_reports(args.report_dir, metadata, rows)
    try:
        base = BaseEngine(settings)
        observe_tokens(base)
        metadata["kernel_backend"] = base.kernel_backend
        metadata["parameters"] = sum(p.numel() for p in base.model.parameters())
        try:
            for length in args.prompt_lengths:
                for index in range(max(args.concurrencies)):
                    text = (f"Document {index + 1}: The river flows through the forest. "
                            "People study the water, trees and weather. Explain the observations. ")
                    seed = base.tokenizer.encode(text, add_special_tokens=False)
                    prompt = (seed * math.ceil(length / len(seed)))[:length]
                    recorder = Recorder()
                    result = base.stream(prompt, args.max_tokens, 0, 1, True, threading.Event(), recorder)
                    if result["completion_tokens"] != args.max_tokens or len(recorder.tokens) != args.max_tokens:
                        raise RuntimeError("Reference generation did not produce the requested tokens")
                    prompts[(length, index)] = prompt
                    expected[(length, index)] = (result, recorder.tokens)
            metadata["dataset"] = [{"prompt_tokens": length, "index": index, "input_ids": prompt,
                                    "output_ids": expected[(length, index)][1],
                                    "output_text": expected[(length, index)][0]["text"]}
                                   for (length, index), prompt in prompts.items()]
        finally:
            base.close()
            del base
        gc.collect()
        if args.device == "cuda":
            torch.cuda.empty_cache()

        with (args.report_dir / "requests.jsonl").open("w") as raw:
            for repetition in range(args.repetitions):
                offset = repetition % len(conditions)
                for condition in conditions[offset:] + conditions[:offset]:
                    with tempfile.TemporaryDirectory(prefix="jamba-benchmark-") as directory:
                        if condition == "base":
                            engine = BaseEngine(settings)
                            backend = engine
                            serial = ThreadPoolExecutor(max_workers=1)
                        else:
                            enabled = condition != "batch"
                            engine = TorchEngine(EngineSettings(
                                **vars(settings), max_parallel=max(args.concurrencies),
                                batch_wait_ms=args.batch_wait_ms, cache_dir=Path(directory), cache_min_prefix=1,
                                cache_gpu_mib=64 if enabled and args.device == "cuda" else 0,
                                cache_ram_mib=256 if enabled else 0, cache_disk_mib=1024 if enabled else 0))
                            backend, serial = engine.backend, None
                        observe_tokens(backend)
                        try:
                            for length in args.prompt_lengths:
                                for concurrency in args.concurrencies:
                                    selected = [prompts[(length, i)] for i in range(concurrency)]
                                    budgets = (backend.cache.gpu_limit, backend.cache.ram_limit) if condition != "base" else None
                                    for wave in range(-1, args.waves):
                                        if condition != "base":
                                            arrange_tier(backend, selected, condition, budgets)
                                        before = counters(backend)
                                        barrier = threading.Barrier(concurrency + 1)
                                        def request(index):
                                            recorder = Recorder()
                                            barrier.wait(timeout=120)
                                            started = time.perf_counter()
                                            arguments = (selected[index], args.max_tokens, 0, 1, True, threading.Event(), recorder)
                                            result = (serial.submit(engine.stream, *arguments).result()
                                                      if serial is not None else engine.stream(*arguments))
                                            elapsed = time.perf_counter() - started
                                            reference, reference_ids = expected[(length, index)]
                                            match = result == reference and recorder.tokens == reference_ids
                                            if result["text"] != "".join(recorder.pieces) or not match:
                                                metadata["output_mismatches"] += 1
                                                raise RuntimeError(f"Output mismatch: {condition}, length={length}, row={index}")
                                            return dict(index=index, latency_ms=elapsed * 1000,
                                                        ttft_ms=(recorder.first_token - started) * 1000,
                                                        completion_tokens=result["completion_tokens"], output_ids=recorder.tokens)

                                        with ThreadPoolExecutor(max_workers=concurrency) as clients:
                                            futures = [clients.submit(request, i) for i in range(concurrency)]
                                            sync()
                                            if args.device == "cuda":
                                                torch.cuda.reset_peak_memory_stats()
                                            started = time.perf_counter()
                                            barrier.wait(timeout=120)
                                            outputs = [future.result() for future in futures]
                                            sync()
                                            elapsed = time.perf_counter() - started
                                        after = counters(backend)
                                        delta = {key: value - before[key] for key, value in after.items()}
                                        restored = (length - 1) * concurrency if condition in {"gpu", "ram", "disk"} else 0
                                        if delta.get("restored_tokens", 0) != restored:
                                            raise RuntimeError(f"Unexpected restored token count: {condition}: {delta}")
                                        if condition in {"gpu", "ram", "disk"} and delta[f"{condition}_hits"] != concurrency:
                                            raise RuntimeError(f"Unexpected cache tier hits: {condition}: {delta}")
                                        if delta.get("errors", 0) or delta.get("disk_errors", 0):
                                            raise RuntimeError(f"Cache errors during measurement: {delta}")
                                        if wave < 0:
                                            continue
                                        latencies = [output["latency_ms"] for output in outputs]
                                        ttfts = [output["ttft_ms"] for output in outputs]
                                        row = dict(condition=condition, repetition=repetition + 1, wave=wave + 1,
                                                   prompt_tokens=length, concurrency=concurrency, requests=concurrency,
                                                   elapsed_seconds=elapsed,
                                                   output_tokens_per_second=sum(o["completion_tokens"] for o in outputs) / elapsed,
                                                   latency_ms=statistics.mean(latencies), ttft_ms=statistics.mean(ttfts),
                                                   latency_p95_ms=percentile(latencies, 0.95), ttft_p95_ms=percentile(ttfts, 0.95),
                                                   latencies_ms=latencies, ttfts_ms=ttfts,
                                                   peak_allocated_mib=torch.cuda.max_memory_allocated() / 1024**2 if args.device == "cuda" else 0,
                                                   peak_reserved_mib=torch.cuda.max_memory_reserved() / 1024**2 if args.device == "cuda" else 0,
                                                   cache_delta=delta)
                                        rows.append(row)
                                        metadata["verified_requests"] += concurrency
                                        for output in outputs:
                                            raw.write(json.dumps({**row, **output}) + "\n")
                                        raw.flush()
                                        print(json.dumps(row), flush=True)
                                        save_reports(args.report_dir, metadata, rows)
                        finally:
                            if serial is not None:
                                serial.shutdown()
                            engine.close()
                            del engine, backend
                            gc.collect()
                            if args.device == "cuda":
                                torch.cuda.empty_cache()
        metadata["status"] = "complete"
    except BaseException as error:
        metadata["status"] = "failed"
        metadata["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
        save_reports(args.report_dir, metadata, rows)


if __name__ == "__main__":
    main()
