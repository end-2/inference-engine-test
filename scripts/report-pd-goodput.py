#!/usr/bin/env python3
"""Recompute separate and joint TTFT and mean TPOT goodput from PD records."""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pd_benchmark", ROOT / "scripts/benchmark-pd.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)
DEFAULT_TTFT = [100, 250, 500, 1000, 2000, 5000, 10000, 20000]
DEFAULT_TPOT = [25, 30, 35, 50]
GROUP = ("ttft_slo_ms", "tpot_slo_ms", "workload", "concurrency", "mode")
RATES = ("request_goodput", "token_goodput", "request_throughput", "token_throughput")


def thresholds(text):
    try:
        values = sorted(set(float(v) for v in text.split(",")))
    except ValueError as error:
        raise argparse.ArgumentTypeError("SLO thresholds must be numbers") from error
    if not values or any(not math.isfinite(v) or v <= 0 for v in values):
        raise argparse.ArgumentTypeError("SLO thresholds must be finite and positive")
    return values


def write_csv(path, rows):
    with path.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def evaluate(records, duration, ttft=None, tpot=None):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("A positive profiling duration is required")
    ttft = math.inf if ttft is None else ttft
    tpot = math.inf if tpot is None else tpot
    good = [r for r in records if r["ttft_ms"] <= ttft and r["tpot_ms"] <= tpot]
    return {"requests": len(records), "good_requests": len(good),
            "ttft_pass": sum(r["ttft_ms"] <= ttft for r in records),
            "tpot_pass": sum(r["tpot_ms"] <= tpot for r in records),
            "good_output_tokens": sum(r["output_tokens"] for r in good),
            "attainment": len(good) / len(records), "duration_seconds": duration,
            "request_goodput": len(good) / duration,
            "token_goodput": sum(r["output_tokens"] for r in good) / duration,
            "request_throughput": len(records) / duration,
            "token_throughput": sum(r["output_tokens"] for r in records) / duration}


def observation_duration(export, records):
    # AIPerf 0.12 uses the observation window for throughput and goodput.
    # Its exported benchmark_duration can differ from that window.
    rps = export["request_throughput"]["avg"]
    if not math.isfinite(rps) or rps <= 0 or not records:
        raise ValueError("A positive request throughput and nonempty records are required")
    duration = len(records) / rps
    tokens = sum(r["output_tokens"] for r in records)
    if not math.isclose(tokens / duration, export["output_token_throughput"]["avg"], rel_tol=1e-7):
        raise ValueError("Request and token throughput imply different observation windows")
    return duration


def summarize(runs):
    groups = defaultdict(list)
    for run in runs:
        groups[tuple(run[key] for key in GROUP)].append(run)
    rows = []
    for key, group in sorted(groups.items()):
        row = dict(zip(GROUP, key))
        row.update(repetitions=len(group), requests=sum(r["requests"] for r in group),
                   good_requests=sum(r["good_requests"] for r in group),
                   ttft_pass=sum(r["ttft_pass"] for r in group), tpot_pass=sum(r["tpot_pass"] for r in group),
                   min_repetition_attainment=min(r["attainment"] for r in group))
        row["attainment"] = row["good_requests"] / row["requests"]
        for metric in RATES:
            row[metric] = statistics.mean(r[metric] for r in group)
            row[metric + "_std"] = statistics.stdev(r[metric] for r in group) if len(group) > 1 else 0
        rows.append(row)
    return rows


def comparisons(rows):
    groups = defaultdict(dict)
    for row in rows:
        groups[tuple(row[key] for key in GROUP[:-1])][row["mode"]] = row
    results = []
    for key, modes in sorted(groups.items()):
        a, d = modes["aggregated"], modes["disaggregated"]
        row = dict(zip(GROUP[:-1], key))
        for prefix, source in (("a", a), ("d", d)):
            for metric in ("request_goodput", "request_goodput_std", "token_goodput", "token_goodput_std",
                           "attainment", "min_repetition_attainment", "good_requests", "requests"):
                row[prefix + "_" + metric] = source[metric]
        row["d_over_a_goodput"] = d["request_goodput"] / a["request_goodput"] if a["request_goodput"] else None
        row["d_minus_a_goodput"] = d["request_goodput"] - a["request_goodput"]
        results.append(row)
    return results


def best_feasible(rows, attainment):
    groups = defaultdict(list)
    keys = ("ttft_slo_ms", "tpot_slo_ms", "workload", "mode")
    for row in rows:
        groups[tuple(row[key] for key in keys)].append(row)
    results = []
    for key, candidates in sorted(groups.items()):
        feasible = [r for r in candidates if r["min_repetition_attainment"] >= attainment]
        best = max(feasible, key=lambda r: (r["request_goodput"], -r["concurrency"])) if feasible else None
        row = dict(zip(keys, key))
        row["attainment_target"] = attainment
        for field in ("concurrency", "request_goodput", "request_goodput_std", "token_goodput",
                      "attainment", "min_repetition_attainment"):
            row[field] = best[field] if best else None
        results.append(row)
    return results


def profile_rows(samples, ttft_values, tpot_values):
    rows = []
    for source, records, duration in samples:
        for ttft in ttft_values:
            for tpot in tpot_values:
                rows.append({"repetition": source["repetition"], "workload": source["workload"],
                             "concurrency": source["concurrency"], "mode": source["mode"],
                             "exported_benchmark_duration_seconds": source["duration_seconds"],
                             "ttft_slo_ms": ttft, "tpot_slo_ms": tpot, **evaluate(records, duration, ttft, tpot)})
    return rows


def write_tables(output, rows, attainment, prefix=""):
    summary = summarize(rows)
    write_csv(output / f"{prefix}run-results.csv", rows)
    write_csv(output / f"{prefix}summary.csv", summary)
    write_csv(output / f"{prefix}comparison.csv", comparisons(summary))
    write_csv(output / f"{prefix}best-feasible.csv", best_feasible(summary, attainment))
    return summary


def load_records(report):
    hashes = {}

    def read(path):
        data = path.read_bytes()
        hashes[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
        return data.decode()

    data = json.loads(read(report / "summary.json"))
    metadata = data["metadata"]
    if metadata["status"] != "complete":
        raise ValueError("Goodput analysis requires a completed paired benchmark")
    runs = json.loads(read(ROOT / metadata["raw_dir"] / "runs.json"))
    complete = benchmark.completed_repetitions(runs, metadata["config"])
    expected_reps = set(range(1, metadata["config"]["repetitions"] + 1))
    if len(complete) != len(runs) or {r["repetition"] for r in runs} != expected_reps:
        raise ValueError("Incomplete or unexpected repetitions")
    samples = []
    max_tpot_difference = 0
    max_duration_difference_pct = 0
    for run in runs:
        artifact = ROOT / run["artifact"]
        export = json.loads(read(artifact))
        if export.get("was_cancelled") or export.get("error_summary") or export.get("error_request_count", {}).get("avg", 0):
            raise ValueError(f"Failed source run: {artifact}")
        benchmark_duration = export["benchmark_duration"]["avg"]
        if export["benchmark_duration"]["unit"] != "sec" or not math.isclose(benchmark_duration, run["duration_seconds"]):
            raise ValueError(f"Duration mismatch: {artifact}")
        inputs = json.loads(read(artifact.parent / "inputs.json"))
        digest = hashlib.sha256(json.dumps([r["payloads"] for r in inputs["data"]], sort_keys=True).encode()).hexdigest()
        if digest != run["dataset_sha256"]:
            raise ValueError(f"Payload mismatch: {artifact}")
        records, ids = [], set()
        for line in read(artifact.parent / "profile_export.jsonl").splitlines():
            record = json.loads(line)
            if record["metadata"]["benchmark_phase"] != "profiling":
                continue
            info, metrics = record["metadata"], record["metrics"]
            request_id = info["x_request_id"]
            if (info.get("was_cancelled") or info.get("context_overflow_skip") or record.get("error")
                    or request_id in ids or metrics["osl_mismatch_diff_pct"]["value"] != 0):
                raise ValueError(f"Invalid or duplicated request: {artifact}")
            ids.add(request_id)
            for name in ("request_latency", "time_to_first_token", "inter_token_latency"):
                if metrics[name]["unit"] != "ms" or not math.isfinite(metrics[name]["value"]):
                    raise ValueError(f"Invalid timing: {artifact}")
            isl, osl = (metrics[k]["value"] for k in ("input_sequence_length", "output_sequence_length"))
            if type(isl) is not int or type(osl) is not int or isl < 1 or osl < 2:
                raise ValueError("TPOT evaluation requires at least two output tokens")
            ttft, latency = (metrics[k]["value"] for k in ("time_to_first_token", "request_latency"))
            if not 0 <= ttft <= latency:
                raise ValueError(f"Invalid TTFT and latency: {artifact}")
            tpot = (latency - ttft) / (osl - 1)
            difference = abs(tpot - metrics["inter_token_latency"]["value"])
            max_tpot_difference = max(max_tpot_difference, difference)
            if difference > 1e-7:
                raise ValueError(f"TPOT differs from recorded ITL: {artifact}")
            records.append({"input_tokens": isl, "output_tokens": osl, "ttft_ms": ttft, "tpot_ms": tpot})
        lengths = Counter(f"{r['input_tokens']}/{r['output_tokens']}" for r in records)
        if len(records) != run["requests"] or len(records) != export["request_count"]["avg"] or lengths != run["length_counts"]:
            raise ValueError(f"Request count or length mismatch: {artifact}")
        duration = observation_duration(export, records)
        max_duration_difference_pct = max(max_duration_difference_pct, abs(duration / benchmark_duration - 1) * 100)
        baseline = evaluate(records, duration, math.inf, math.inf)
        for field, tag in (("request_throughput", "request_throughput"), ("token_throughput", "output_token_throughput")):
            if not math.isclose(baseline[field], export[tag]["avg"], rel_tol=1e-7):
                raise ValueError(f"Baseline throughput mismatch: {artifact}")
        samples.append((run, records, duration))
    if sum(len(records) for _, records, _ in samples) != metadata["measured_requests"]:
        raise ValueError("Total measured request count mismatch")
    return metadata, samples, hashes, max_tpot_difference, max_duration_difference_pct


def plot(output, rows, ttft_values, tpot_values):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    workloads = [w for w in ("i704-o16", "i704-o256", "mixed") if any(r["workload"] == w for r in rows)]
    if not workloads:
        workloads = sorted({r["workload"] for r in rows})[:3]
    focused = [x for x in (30, 35) if x in tpot_values] or tpot_values[:2]
    concurrency = max(r["concurrency"] for r in rows)
    values = {(r["workload"], r["concurrency"], r["mode"], r["ttft_slo_ms"], r["tpot_slo_ms"]): r for r in rows}
    fig, axes = plt.subplots(len(focused), len(workloads), figsize=(13, 4 * len(focused)), squeeze=False)
    for y, tpot in enumerate(focused):
        for x, workload in enumerate(workloads):
            ax = axes[y, x]
            for mode, label, color in (("aggregated", "Aggregated", "#2563eb"), ("disaggregated", "Disaggregated", "#e07a24")):
                selected = [values[workload, concurrency, mode, ttft, tpot] for ttft in ttft_values]
                ax.errorbar([t / 1000 for t in ttft_values], [r["request_goodput"] for r in selected],
                            yerr=[r["request_goodput_std"] for r in selected], marker="o", markersize=4,
                            capsize=3, label=label, color=color)
            ax.set_xscale("log")
            ax.set_ylim(bottom=0)
            ax.set_title(f"{workload} | mean TPOT <= {tpot:g} ms")
            ax.set_xlabel("TTFT SLO (seconds, log scale)")
            ax.set_ylabel("SLO-compliant requests / second")
            ax.grid(alpha=0.2)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.955), ncol=2, frameon=False)
    fig.suptitle(f"Concurrency {concurrency}: joint TTFT and mean TPOT goodput", weight="bold")
    fig.text(0.5, 0.012, "Same recorded requests | Mean of repeated runs, error bars: sample SD | No attainment gate in this figure", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.035, 1, 0.92))
    fig.savefig(output / "goodput-slo.png", dpi=180, facecolor="white")
    plt.close(fig)


def plot_separate(output, summaries, limits):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    available = {r["workload"] for r in summaries["ttft"]}
    workloads = [w for w in ("i704-o16", "i704-o256", "mixed") if w in available] or sorted(available)[:3]
    concurrency = max(r["concurrency"] for r in summaries["ttft"])
    fig, axes = plt.subplots(2, len(workloads), figsize=(13, 8), squeeze=False)
    for y, criterion in enumerate(("ttft", "tpot")):
        values = {(r["workload"], r["mode"], r[criterion + "_slo_ms"]): r
                  for r in summaries[criterion] if r["concurrency"] == concurrency}
        for x, workload in enumerate(workloads):
            ax = axes[y, x]
            for mode, label, color in (("aggregated", "Aggregated", "#2563eb"), ("disaggregated", "Disaggregated", "#e07a24")):
                selected = [values[workload, mode, threshold] for threshold in limits[criterion]]
                ax.errorbar([t / 1000 if criterion == "ttft" else t for t in limits[criterion]],
                            [r["request_goodput"] for r in selected],
                            yerr=[r["request_goodput_std"] for r in selected],
                            marker="o", markersize=4, capsize=3, color=color, label=label)
            if criterion == "ttft":
                ax.set_xscale("log")
                ax.set_xlabel("TTFT limit (seconds, log scale); TPOT unrestricted")
            else:
                ax.set_xticks(limits[criterion])
                ax.set_xlabel("Mean TPOT limit (ms); TTFT unrestricted")
            ax.set_ylim(bottom=0)
            ax.set_title(f"{workload} | {criterion.upper()} only")
            ax.set_ylabel("SLO-compliant requests / second")
            ax.grid(alpha=0.2)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.955), ncol=2, frameon=False)
    fig.suptitle(f"Concurrency {concurrency}: separate TTFT and mean TPOT goodput", weight="bold")
    fig.text(0.5, 0.012, "Same full observation window for both metrics | Mean of repeated runs, error bars: sample SD | No attainment gate", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.035, 1, 0.92))
    fig.savefig(output / "goodput-separated.png", dpi=180, facecolor="white")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", type=Path)
    parser.add_argument("--ttft-ms", type=thresholds, default=DEFAULT_TTFT)
    parser.add_argument("--tpot-ms", type=thresholds, default=DEFAULT_TPOT)
    parser.add_argument("--min-attainment", type=float, default=0.95)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if not 0 < args.min_attainment <= 1:
        parser.error("--min-attainment must be in (0, 1]")
    report = args.report_dir.resolve()
    output = (args.output_dir or report / "goodput").resolve()
    metadata, samples, hashes, difference, duration_difference = load_records(report)
    output.mkdir(parents=True, exist_ok=True)
    summary = write_tables(output, profile_rows(samples, args.ttft_ms, args.tpot_ms), args.min_attainment)
    separate = {
        "ttft": write_tables(output, profile_rows(samples, args.ttft_ms, [None]), args.min_attainment, "ttft-"),
        "tpot": write_tables(output, profile_rows(samples, [None], args.tpot_ms), args.min_attainment, "tpot-")}
    benchmark.write_json(output / "source-sha256.json", hashes)
    benchmark.write_json(output / "metadata.json", {
        "source_report": str(report.relative_to(ROOT)), "source_run_id": metadata["run_id"],
        "measured_requests": sum(len(r) for _, r, _ in samples), "source_runs": len(samples),
        "workers": metadata.get("workers"), "ttft_slo_ms": args.ttft_ms, "tpot_slo_ms": args.tpot_ms,
        "joint_slo_comparison": "TTFT <= threshold AND mean TPOT <= threshold",
        "separate_slo_comparisons": {
            "ttft": "TTFT <= threshold; TPOT unrestricted",
            "tpot": "mean TPOT <= threshold; TTFT unrestricted"},
        "inactive_slo_csv_value": "Empty threshold cell means unrestricted; its pass count equals request count",
        "separate_goodput_duration": "Same full observation window as joint goodput; no subtraction of TTFT or queue time",
        "tpot_definition": "(request_latency_ms - ttft_ms) / (output_tokens - 1)",
        "request_goodput_definition": "slo_compliant_requests / throughput_observation_duration_seconds",
        "token_goodput_definition": "sum(output_tokens_of_slo_compliant_requests) / throughput_observation_duration_seconds",
        "observation_duration_definition": "profiling_request_count / exported_request_throughput; verified against exported output token throughput",
        "aggregation": "Arithmetic mean of per-run goodputs; sample SD; request-weighted attainment",
        "best_feasible_rule": "Max mean request goodput among tested concurrencies with attainment >= target in EVERY repetition",
        "attainment_target": args.min_attainment, "warmup_excluded": True,
        "payloads_verified": True, "length_counts_verified": True, "baseline_throughput_verified": True,
        "max_tpot_vs_recorded_itl_difference_ms": difference,
        "max_observation_vs_benchmark_duration_difference_pct": duration_difference})
    plot(output, summary, args.ttft_ms, args.tpot_ms)
    plot_separate(output, separate, {"ttft": args.ttft_ms, "tpot": args.tpot_ms})
    print(f"Validated {sum(len(r) for _, r, _ in samples)} requests; wrote {len(summary)} joint, "
          f"{len(separate['ttft'])} TTFT-only, {len(separate['tpot'])} TPOT-only summaries to {output}")


if __name__ == "__main__":
    main()
