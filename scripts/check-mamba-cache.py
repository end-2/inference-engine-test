#!/usr/bin/env python3
"""Compare Mamba generation with cold, warm and restarted prefix checkpoints."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--dtype", choices=("float32", "float16", "bfloat16"))
    parser.add_argument("--prompt-lengths", default="64,256")
    parser.add_argument("--max-tokens", type=int, default=16)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        lengths = [int(value) for value in args.prompt_lengths.split(",")]
        if min(lengths) < 2 or min(args.max_tokens, args.repetitions) < 1 or len(set(lengths)) != len(lengths):
            raise ValueError
    except ValueError:
        parser.error("prompt lengths must be distinct integers >= 2; token limit and repetitions must be positive")

    import torch
    import transformers
    from huggingface.mamba.base.engine import EngineSettings, TorchEngine
    from huggingface.mamba.cache.engine import EngineSettings as CacheSettings, TorchEngine as CacheEngine

    settings = EngineSettings(args.model, n_ctx=max(lengths) + args.max_tokens,
                              device=args.device, dtype=args.dtype)
    base = TorchEngine(settings)
    rows, expected, prompts = [], {}, {}
    kernel_backend = base.kernel_backend
    seed = base.prepare_prompt([{"role": "user", "content":
        "The river flows through the forest. People study the water and the trees. "}])
    for length in lengths:
        prompts[length] = (seed * ((length + len(seed) - 1) // len(seed)))[:length]

    def sync():
        if args.device == "cuda":
            torch.cuda.synchronize()

    def measure(engine, label, length, repetition):
        pieces, first_text = [], []

        def emit(text):
            if not first_text:
                first_text.append(time.perf_counter())
            pieces.append(text)

        before = getattr(engine, "restored_tokens", 0)
        sync()
        started = time.perf_counter()
        result = engine.stream(prompts[length], args.max_tokens, 0, 1, True, threading.Event(), emit)
        sync()
        elapsed = time.perf_counter() - started
        if "".join(pieces) != result["text"] or result["completion_tokens"] != args.max_tokens:
            raise RuntimeError("Incomplete or inconsistent streaming result")
        if label == "base":
            if length in expected and expected[length] != result:
                raise RuntimeError("Nondeterministic baseline output")
            expected[length] = result
        elif result != expected[length]:
            raise RuntimeError(f"Output differs from baseline: {label}, prompt length {length}")
        restored = getattr(engine, "restored_tokens", 0) - before
        if label in {"warm", "disk-restart"} and restored != length - 1:
            raise RuntimeError(f"Expected a full checkpoint hit, restored {restored} tokens")
        if label in {"base", "cold"} and restored:
            raise RuntimeError("Unexpected prefix reuse in baseline or cold request")
        row = {"condition": label, "prompt_tokens": length, "repetition": repetition,
               "completion_tokens": result["completion_tokens"], "restored_tokens": restored,
               "latency_ms": elapsed * 1000,
               "first_text_ms": (first_text[0] - started) * 1000 if first_text else None,
               "output_tokens_per_second": result["completion_tokens"] / elapsed,
               "output_sha256": hashlib.sha256(result["text"].encode()).hexdigest()}
        rows.append(row)
        print(json.dumps(row), flush=True)

    try:
        base.complete(prompts[lengths[0]], args.max_tokens, 0, 1, True, threading.Event())
        for length in lengths:
            for repetition in range(args.repetitions):
                measure(base, "base", length, repetition + 1)
    finally:
        base.close()
    if args.device == "cuda":
        torch.cuda.empty_cache()
    with tempfile.TemporaryDirectory() as directory:
        cache_settings = CacheSettings(**asdict(settings), cache_dir=Path(directory),
                                       cache_min_prefix=1, cache_ram_mib=64, cache_disk_mib=64)
        engine = CacheEngine(cache_settings)
        try:
            engine.complete(prompts[lengths[0]], args.max_tokens, 0, 1, True, threading.Event())
            for length in lengths:
                for repetition in range(args.repetitions):
                    for tokens in list(engine.cache.ram) + list(engine.cache.disk):
                        engine.cache.discard(tokens)
                    measure(engine, "cold", length, repetition + 1)
                    measure(engine, "warm", length, repetition + 1)
            # Save every tested prefix for the restart check.
            for length in lengths:
                engine.complete(prompts[length], 1, 0, 1, True, threading.Event())
            cache_stats = dict(engine.cache.stats)
            state_sizes = {str(len(key)): len(snapshot.state) for key, snapshot in engine.cache.ram.items()}
        finally:
            engine.close()
        engine = CacheEngine(cache_settings)
        try:
            for length in lengths:
                measure(engine, "disk-restart", length, 1)
            disk_hits = engine.cache.stats["disk_hits"]
            if disk_hits != len(lengths):
                raise RuntimeError("Disk checkpoints were not restored")
        finally:
            engine.close()

    summary = []
    for length in lengths:
        for condition in ("base", "cold", "warm", "disk-restart"):
            group = [r for r in rows if r["prompt_tokens"] == length and r["condition"] == condition]
            summary.append({"condition": condition, "prompt_tokens": length, "runs": len(group),
                            **{f"{metric}_mean": statistics.mean(row[metric] for row in group)
                               for metric in ("latency_ms", "first_text_ms", "output_tokens_per_second")}})
    report = {"status": "passed", "created_at": datetime.now(timezone.utc).isoformat(),
              "model": str(args.model), "device": args.device, "dtype": settings.dtype,
              "torch": torch.__version__, "transformers": transformers.__version__,
              "gpu": torch.cuda.get_device_name() if args.device == "cuda" else None,
              "kernel_backend": kernel_backend, "max_tokens": args.max_tokens,
              "cache_stats_before_close": cache_stats, "restart_disk_hits": disk_hits,
              "snapshot_bytes_by_prefix_length": state_sizes, "summary": summary, "requests": rows,
              "measurement": "Serial engine calls, greedy decoding, no HTTP or queueing. First text is the first nonempty TextStreamer callback, not first generated token. Loading and initial warmup are excluded; cold includes snapshot serialization. Disk restart has one sample per length."}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: {args.report}", flush=True)


if __name__ == "__main__":
    main()
