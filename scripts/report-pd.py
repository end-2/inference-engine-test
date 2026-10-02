#!/usr/bin/env python3
"""Create paired comparisons and figures from validated PD repetitions."""

import argparse
from collections import defaultdict
from copy import deepcopy
import csv
import importlib.util
import json
from pathlib import Path
import shlex
import statistics

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pd_benchmark", ROOT / "scripts/benchmark-pd.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def workload_key(name):
    if name == "mixed":
        return (10**9, 0)
    left, right = name.split("-")
    return int(left[1:]), int(right[1:])


def compare(results):
    groups = defaultdict(dict)
    for row in results:
        groups[(row["workload"], row["concurrency"])][row["mode"]] = row
    rows = []
    for (workload, concurrency), modes in sorted(groups.items(), key=lambda p: (workload_key(p[0][0]), p[0][1])):
        a, d = modes["aggregated"], modes["disaggregated"]
        row = {"workload": workload, "concurrency": concurrency,
               "actual_input_tokens_avg": a["input_tokens_avg"], "actual_output_tokens_avg": a["output_tokens_avg"],
               "a_requests": a["requests"], "d_requests": d["requests"],
               "a_output_tok_s": a["output_tokens_per_second"], "d_output_tok_s": d["output_tokens_per_second"],
               "d_over_a_throughput": d["output_tokens_per_second"] / a["output_tokens_per_second"],
               "d_throughput_change_pct": (d["output_tokens_per_second"] / a["output_tokens_per_second"] - 1) * 100,
               "a_ttft_ms": a["ttft_avg_ms"], "d_ttft_ms": d["ttft_avg_ms"],
               "a_latency_ms": a["latency_avg_ms"], "d_latency_ms": d["latency_avg_ms"],
               "a_latency_p95_ms": a["latency_p95_ms"], "d_latency_p95_ms": d["latency_p95_ms"],
               "a_itl_ms": a["itl_avg_ms"], "d_itl_ms": d["itl_avg_ms"]}
        rows.append(row)
    return rows


def figures(report, results, comparisons, metadata):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    import numpy as np

    config = metadata["config"]
    output = report / "figures"
    output.mkdir(exist_ok=True)
    workloads = sorted({r["workload"] for r in results}, key=workload_key)
    concurrencies = config["concurrencies"]
    pairs = {(r["workload"], r["concurrency"]): r for r in comparisons}
    matrix = np.array([[pairs[w, c]["d_over_a_throughput"] for c in concurrencies] for w in workloads])
    labels = [w.replace("i", "").replace("-o", " / ") if w != "mixed" else "Mixed" for w in workloads]
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(8, 7.5))
    norm = TwoSlopeNorm(vmin=min(0.25, float(matrix.min())), vcenter=1, vmax=max(1.2, float(matrix.max())))
    im = ax.imshow(matrix, cmap="RdYlGn", norm=norm, aspect="auto")
    ax.set_xticks(range(len(concurrencies)), concurrencies)
    ax.set_yticks(range(len(workloads)), labels)
    ax.set_xlabel("Concurrency")
    ax.set_ylabel("Synthetic input / requested output tokens")
    ax.set_title("Disaggregated / aggregated output throughput", loc="left", weight="bold", pad=16)
    for y in range(len(workloads)):
        for x in range(len(concurrencies)):
            ax.text(x, y, f"{matrix[y, x]:.2f}x", ha="center", va="center", color="#161616", weight="bold")
    fig.colorbar(im, ax=ax, label="Ratio: above 1 favors disaggregation", shrink=0.8)
    gpu = metadata["gpu"].split(",", 1)[0]
    fig.text(0.5, 0.045, f"SmolLM2-135M | {gpu} | {metadata.get('mps_slots', 2)} MPS shares | FP16 | HTTP KV transfer", ha="center", fontsize=9)
    fig.text(0.5, 0.02, f"{config['repetitions']} run(s) per mode | {config['requests']} measured requests per run and condition", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(output / "throughput-ratio.png", dpi=180, facecolor="white")
    plt.close(fig)

    largest = max(concurrencies)
    by_mode = {(r["workload"], r["concurrency"], r["mode"]): r for r in results}
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.5), sharey=True)
    y = np.arange(len(workloads))
    for ax, (metric, axis_label) in zip(axes, (("output_tokens_per_second", "Output tokens / second"),
                                               ("ttft_avg_ms", "Mean TTFT (ms)"))):
        for mode, offset, color, label in (("aggregated", -0.18, "#2563eb", "Aggregated"),
                                           ("disaggregated", 0.18, "#e07a24", "Disaggregated")):
            values = [by_mode[w, largest, mode][metric] for w in workloads]
            errors = [by_mode[w, largest, mode][metric + "_std"] for w in workloads]
            ax.barh(y + offset, values, height=0.33, xerr=errors if config["repetitions"] > 1 else None,
                    color=color, label=label, capsize=3)
        ax.set_xlabel(axis_label)
        ax.grid(axis="x", alpha=0.2)
        ax.set_axisbelow(True)
    axes[0].set_yticks(y, labels)
    axes[0].invert_yaxis()
    axes[0].set_ylabel("Synthetic input / requested output tokens")
    detail = f"mean of {config['repetitions']} runs with sample SD" if config["repetitions"] > 1 else "one measured run per mode"
    fig.suptitle(f"Concurrency {largest}: {detail}", weight="bold", y=0.99)
    handles, legend_labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="upper center", bbox_to_anchor=(0.5, 0.955), ncol=2, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    fig.savefig(output / "throughput-ttft.png", dpi=180, facecolor="white")
    plt.close(fig)


def phase_diagnostics(raw, repetitions):
    groups = defaultdict(list)
    selected = {f"r{number}" for number in repetitions}
    for path in raw.glob("r*/*/workers.log"):
        if path.parent.parent.name not in selected:
            continue
        mode = path.parent.name
        for line in path.read_text().splitlines():
            if "pd_request " not in line:
                continue
            record = json.loads(line.split("pd_request ", 1)[1])
            if mode == "disaggregated":
                groups[(record["prompt_tokens"], record["completion_tokens"])].append(record)
    result = []
    metrics = ("prefill_ms", "decode_ms", "export_ms", "import_ms", "prefill_rpc_ms", "state_receive_ms", "state_bytes")
    for (isl, osl), group in sorted(groups.items()):
        queues = {}
        for key in ("prefill_queue_ms", "decode_queue_ms", "state_queue_ms"):
            if all(key in record for record in group):
                queues[key] = statistics.mean(record[key] for record in group)
        result.append({"input_tokens": isl, "output_tokens": osl, "requests_including_warmup": len(group),
                       **{key: statistics.mean(r[key] for r in group) for key in metrics}, **queues})
    return result


def scheduler_diagnostics(raw, metadata):
    groups = defaultdict(list)
    requests = defaultdict(list)
    config = metadata["scheduler_config"]
    for path in raw.glob("r*/*/workers.log"):
        if metadata.get("included_repetitions") and int(path.parent.parent.name[1:]) not in metadata["included_repetitions"]:
            continue
        for line in path.read_text().splitlines():
            if "pd_request " in line:
                record = json.loads(line.split("pd_request ", 1)[1])
                requests[record["role"]].append(record)
            if "pd_scheduler " not in line:
                continue
            role = next((r for r in ("aggregate", "prefill", "decode") if f"pd-{r}-" in line), None)
            if role is None:
                raise ValueError(f"Missing scheduler worker role in {path}")
            record = json.loads(line.split("pd_scheduler ", 1)[1])
            tokens = record["prefill_tokens"] + record["decode_tokens"]
            if not (tokens == record["scheduled_tokens"] <= record["token_budget"] == config["token_budget"]
                    and 0 < record["requests"] <= config["max_num_seqs"]):
                raise ValueError(f"Scheduler budget violation in {path}")
            if (role == "prefill" and record["decode_tokens"]) or (role == "decode" and record["prefill_tokens"]):
                raise ValueError(f"Scheduler role violation in {path}")
            groups[role].append(record)
    if set(groups) != {"aggregate", "prefill", "decode"}:
        raise ValueError("Missing scheduler traces for one or more roles")
    output = {}
    for role, records in sorted(groups.items()):
        mixed = [r for r in records if r["prefill_tokens"] and r["decode_tokens"]]
        output[role] = {
            "steps_including_warmup": len(records), "mixed_steps": len(mixed),
            "requests_max": max(r["requests"] for r in records),
            "requests_mean": statistics.mean(r["requests"] for r in records),
            "scheduled_tokens_max": max(r["scheduled_tokens"] for r in records),
            "prefill_tokens": sum(r["prefill_tokens"] for r in records),
            "decode_tokens": sum(r["decode_tokens"] for r in records),
            "step_ms_mean": statistics.mean(r["step_ms"] for r in records),
            "mixed_step_decode_budget_fraction_mean": (statistics.mean(
                r["decode_tokens"] / r["token_budget"] for r in mixed) if mixed else None),
        }
    if (output["aggregate"]["prefill_tokens"] != sum(r["prompt_tokens"] for r in requests["aggregated"])
            or output["aggregate"]["decode_tokens"] != sum(r["completion_tokens"] - 1 for r in requests["aggregated"])
            or output["prefill"]["prefill_tokens"] != sum(r["prompt_tokens"] for r in requests["decode"])
            or output["decode"]["decode_tokens"] != sum(r["completion_tokens"] for r in requests["decode"])):
        raise ValueError("Scheduler token counts differ from completed requests; inspect trace completeness")
    return {"budget_and_role_checks_passed": True, "computed_token_totals_match_requests": True,
            "roles": output}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", type=Path)
    parser.add_argument("--completed-only", action="store_true",
                        help="Report full paired repetitions from an interrupted sweep, preserving its failed status")
    args = parser.parse_args()
    report = args.report_dir.resolve()
    data = json.loads((report / "summary.json").read_text())
    metadata, results = deepcopy(data["metadata"]), data["results"]
    if metadata["status"] != "complete" and not args.completed_only:
        parser.error("The PD sweep must be complete, or select --completed-only explicitly")
    runs_file = ROOT / metadata["raw_dir"] / "runs.json"
    if not runs_file.exists():
        parser.error("No validated measurements are available")
    runs = json.loads(runs_file.read_text())
    prefix = "summary"
    if metadata["status"] != "complete":
        try:
            runs = benchmark.completed_repetitions(runs, metadata["config"])
        except ValueError as exc:
            parser.error(str(exc))
        repetitions = sorted({r["repetition"] for r in runs})
        metadata.update(source_status=metadata["status"], status="partial",
                        requested_repetitions=metadata["config"]["repetitions"], included_repetitions=repetitions,
                        measured_requests=sum(r["requests"] for r in runs), errors=sum(r["errors"] for r in runs))
        metadata["config"]["repetitions"] = len(repetitions)
        metadata["mode_order"] = [metadata["mode_order"][r - 1] for r in repetitions]
        results = benchmark.summarize(runs)
        prefix = "completed-summary"
        benchmark.write_json(report / f"{prefix}.json", {"metadata": metadata, "results": results})
        with (report / f"{prefix}.csv").open("w") as output:
            writer = csv.DictWriter(output, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
    config = metadata["config"]
    benchmark.write_json(report / "workload.json", config)
    comparisons = compare(results)
    with (report / "comparison.csv").open("w") as output:
        writer = csv.DictWriter(output, fieldnames=list(comparisons[0]))
        writer.writeheader()
        writer.writerows(comparisons)
    figures(report, results, comparisons, metadata)
    included = metadata.get("included_repetitions", list(range(1, config["repetitions"] + 1)))
    diagnostics = phase_diagnostics(ROOT / metadata["raw_dir"], included)
    (report / "phase-diagnostics.json").write_text(json.dumps(diagnostics, indent=2) + "\n")
    largest = max(config["concurrencies"])
    high = [r for r in comparisons if r["concurrency"] == largest]
    wins = sum(r["d_over_a_throughput"] > 1 for r in comparisons)
    order = ", ".join("→".join("A" if m == "aggregated" else "D" for m in pair)
                      for pair in metadata["mode_order"])
    mixed = next((r for r in runs if r["mode"] == "aggregated" and r["workload"] == "mixed"), None)
    mixture = ", ".join(f"{pair}토큰 {count}개" for pair, count in mixed["length_counts"].items()) if mixed else "없음"
    slots = metadata.get("mps_slots", 2)
    workers = metadata.get("workers", benchmark.profile(slots)["workers"])
    scheduled = metadata.get("scheduler") == "token-budget"
    if scheduled:
        diagnostics = scheduler_diagnostics(ROOT / metadata["raw_dir"], metadata)
        benchmark.write_json(report / "scheduler-diagnostics.json", diagnostics)
    scheduling = (f"Greedy decoding, EOS 억제, RUNNING 우선 continuous batching, "
                  f"step당 token budget {metadata['scheduler_config']['token_budget']}, "
                  f"max_num_seqs {metadata['scheduler_config']['max_num_seqs']}, prefix cache 비활성화입니다."
                  if scheduled else "Greedy decoding, EOS 억제, 요청별 batch 1, prefix cache와 continuous batching 비활성화입니다.")
    lines = ["# Aggregation과 Prefill/Decode disaggregation 성능 비교", "",
             f"SmolLM2-135M-Instruct, FP16, GPU: `{metadata['gpu']}`.", "",
             f"집계에 포함한 측정 요청은 {metadata['measured_requests']:,}개이며, 이 요청들의 오류는 {metadata['errors']}개입니다. "
             f"입력과 출력 조합 {len(comparisons) // len(config['concurrencies'])}개, 동시성 {config['concurrencies']}, "
             f"{config['repetitions']}회 반복이며 조건과 반복별 {config['requests']}개 요청을 측정했습니다.", "",
             f"Disaggregation의 평균 처리량이 aggregation보다 높은 조건은 {len(comparisons)}개 중 {wins}개입니다. "
             f"이는 단일 GPU의 MPS share {slots}개와 CPU 메모리를 경유하는 HTTP 상태 전달 구현에 대한 결과입니다.", "",
             f"동시성 {largest}에서 disaggregation / aggregation 처리량 비율은 "
             f"{min(r['d_over_a_throughput'] for r in high):.2f}x부터 {max(r['d_over_a_throughput'] for r in high):.2f}x입니다.", "",
             "![처리량 비율](figures/throughput-ratio.png)", "",
             f"## 동시성 {largest} 비교", "",
             "A는 aggregation, D는 disaggregation입니다. 입력 길이는 합성 텍스트 기준이며 실제 사용량은 표에 별도로 표시합니다.", "",
             "| 입력/출력 | 실제 입력 평균 | A tok/s | D tok/s | D 변화 | A TTFT ms | D TTFT ms | A p95 지연 ms | D p95 지연 ms |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    if metadata["status"] == "partial":
        lines[2:2] = [f"**{metadata['requested_repetitions']}회 반복 계획 중 완료된 {config['repetitions']}회의 전체 workload 비교입니다.** "
                      "추가 반복은 중단됐으며 실패한 반복은 성능 집계에서 제외했습니다. "
                      "[원본 실행 상태](summary.json)는 실패 상태로 보존합니다.", ""]
    for r in high:
        label = r["workload"].replace("i", "").replace("-o", "/") if r["workload"] != "mixed" else "혼합"
        lines.append(f"| {label} | {r['actual_input_tokens_avg']:.1f} | {r['a_output_tok_s']:.2f} | {r['d_output_tok_s']:.2f} | "
                     f"{r['d_throughput_change_pct']:+.1f}% | {r['a_ttft_ms']:.1f} | {r['d_ttft_ms']:.1f} | "
                     f"{r['a_latency_p95_ms']:.1f} | {r['d_latency_p95_ms']:.1f} |")
    lines += ["", "![처리량과 TTFT](figures/throughput-ttft.png)", "", "## 측정 조건", "",
              f"- Aggregation: 전체 추론 worker {workers['aggregated']}개. Disaggregation: Prefill worker {workers['prefill']}개와 Decode worker {workers['decode']}개.",
              "- 각 worker는 MPS share 1개, CPU 요청 1과 상한 2, 메모리 2 GiB를 사용합니다. 두 mode 모두 같은 CPU router를 사용합니다.",
              f"- 물리 GPU 하나를 MPS share {slots}개로 나누며 client별 active thread 한도는 {100 // slots}%입니다.",
              "- " + scheduling,
              f"- 합성 입력 {config['input_tokens']}, 출력 {config['output_tokens']}의 모든 조합을 측정했습니다. 혼합 분포는 `{config.get('mixed_distribution') or '없음'}`입니다.",
              f"- AIPerf 0.12.0, seed {config['seed']}, 데이터셋 {config['dataset_entries']}개, sequential sampling을 사용했습니다.",
              f"- 혼합 부하에서 실제 측정된 입력/출력별 반복당 요청 수는 {mixture}입니다. 설정의 확률과 유한 데이터셋의 실제 비중은 다를 수 있습니다.",
              f"- 각 조건의 워밍업 {config['warmup_requests']}개는 통계에서 제외했습니다. 배포, 모델 로딩과 AIPerf 시작 시간도 처리량에서 제외합니다.",
              f"- 반복별 mode 순서는 {order}입니다. 두 mode의 요청 payload 해시와 실제 입력, 출력 길이별 요청 수가 동일한지 검사했습니다.",
              "- 출력 길이가 요청값과 다르거나 요청 오류가 있으면 해당 실행을 성공 결과로 저장하지 않습니다.", "",
              "## 지표와 해석 범위", "",
              "처리량, 평균 지연, 평균 TTFT와 ITL은 반복별 AIPerf 지표를 산술 평균했습니다. " +
              ("표준편차는 반복 간 sample SD입니다. " if config["repetitions"] > 1 else "1회 측정이므로 반복 간 변동성은 추정하지 않습니다. ") +
              "p95 지연과 p95 TTFT는 같은 조건의 모든 반복 요청을 합쳐 nearest-rank로 계산했습니다. "
              f"조건별 mode당 표본은 {config['requests'] * config['repetitions']}개이며 긴 꼬리 지연의 정밀 추정에는 더 많은 표본이 필요합니다.", "",
              "TTFT는 첫 텍스트 chunk 도착까지의 시간이며 대기열, tokenization과 HTTP 전달을 포함합니다. "
              "TextStreamer의 단어 버퍼 때문에 첫 GPU 토큰 생성 시간과 다를 수 있습니다. ITL은 AIPerf의 streaming 지표입니다.", "",
              "분리 경로는 GPU KV cache를 CPU로 복사한 뒤 Prefill→Router→Decode의 HTTP 경로로 보냅니다. " +
              ("Decode는 첫 출력 생성을 위해 마지막 prompt 토큰 1개를 다시 계산합니다. " if scheduled else
               "Decode는 프롬프트를 다시 계산하지 않습니다. ") +
              "첫 토큰 선택도 Decode worker에서 수행하므로 TTFT에는 Decode 대기열이 포함됩니다. "
              f"Aggregation의 {workers['aggregated']}개 worker는 각각 decode를 수행하고 분리 구성에는 decode worker가 {workers['decode']}개입니다. "
              "긴 출력의 처리량, 전송 비용과 높은 동시성의 대기 시간을 이 조건에 맞춰 해석해야 합니다.", "",
              ("Packed SDPA와 요청별 KV 복사를 사용하며 vLLM의 PagedAttention, CUDA graph, 비동기 실행이나 preemption은 구현하지 않았습니다. "
               "이 결과를 vLLM 자체의 성능으로 해석하지 않습니다." if scheduled else
               "RDMA, NVLink 또는 CUDA IPC를 사용한 전송, continuous batching, 대형 모델과 다중 물리 GPU의 성능으로 일반화하지 않습니다."), "",
              "## 원본과 재현", "",
              f"[집계 CSV]({prefix}.csv), [조건별 A/D 비교](comparison.csv), [집계 설정과 검증 JSON]({prefix}.json), "
              "[worker 단계별 진단](phase-diagnostics.json)에 수치가 있습니다. 단계별 진단은 워밍업을 포함한 worker 로그의 평균이며 AIPerf 측정 통계와 분리합니다.", "",
              f"요청별 AIPerf exports, payload, GPU 표본과 Pod 로그는 저장소의 `{metadata['raw_dir']}`에 보관합니다. "
              "원본 경로는 Git에서 제외됩니다.", "",
              "```sh", "python3 scripts/benchmark-pd.py " +
              f"--mps-replicas {slots} --cluster {shlex.quote(metadata['cluster'])} " +
              (f"--scheduler token-budget --token-budget {metadata['scheduler_config']['token_budget']} " if scheduled else "") +
              f"--config {shlex.quote(str(report.relative_to(ROOT) / 'workload.json'))}",
              f"python3 scripts/report-pd.py {shlex.quote(str(report.relative_to(ROOT)))}" +
              (" --completed-only" if metadata["status"] == "partial" else ""), "```", "",
              "준비와 설정은 [PD 비교 가이드](../../../../guides/" +
              ("prefill-decode-4.md" if slots == 4 else "prefill-decode.md") + ")를 참고합니다.", ""]
    if (report / "environment-validation.json").exists():
        lines += ["실행 환경과 기존 환경 복구 검사는 "
                  "[환경 검증 결과](environment-validation.json)에 기록합니다.", ""]
    if (report / "stability.md").exists():
        lines += ["중단 원인과 수정 후 검증은 [안정성 분석](stability.md)을 참고합니다.", ""]
    if (report / "analysis.md").exists():
        lines += ["처리량과 지연 차이의 원인은 [성능 원인 분석](analysis.md)을 참고합니다.", ""]
    if (report / "validation.md").exists():
        lines += ["배포 검증 범위와 기존 환경 보존 확인은 [구성 검증](validation.md)을 참고합니다.", ""]
    if (report / "goodput/summary.md").exists():
        lines += ["요청별 TTFT와 TPOT 임계값에 따른 결과는 [Goodput 비교](goodput/summary.md)를 참고합니다.", ""]
    if scheduled:
        lines += ["스케줄링 token budget, 요청 수 상한과 역할별 prefill/decode 분리는 "
                  "[step 로그 검증](scheduler-diagnostics.json)에 기록합니다. 워밍업을 포함한 로그입니다.", ""]
    (report / "summary.md").write_text("\n".join(lines))
    print(report / "summary.md")


if __name__ == "__main__":
    main()
