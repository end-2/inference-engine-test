#!/usr/bin/env python3
"""Plot a completed hybrid benchmark with matplotlib."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", type=Path)
    args = parser.parse_args()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    metadata = json.loads((args.report_dir / "run.json").read_text())
    if metadata["status"] != "complete":
        parser.error("The benchmark must be complete")
    rows = [json.loads(line) for line in (args.report_dir / "summary.jsonl").read_text().splitlines()]
    lengths = sorted({row["prompt_tokens"] for row in rows})
    styles = {"base": ("#52525b", "Base serial"), "batch": ("#2563eb", "Batch, cache off"),
              "cold": ("#ea580c", "Cold cache"), "gpu": ("#15803d", "GPU hit"),
              "ram": ("#0891b2", "RAM hit"), "disk": ("#9333ea", "Disk hit")}
    fig, axes = plt.subplots(len(lengths), 2, figsize=(12, 4 * len(lengths)), squeeze=False)
    for index, length in enumerate(lengths):
        for column, (metric, label) in enumerate((("output_tokens_per_second", "Output tokens / second"),
                                                  ("ttft_ms", "Time to first token (ms, log scale)"))):
            axis = axes[index, column]
            for condition, (color, name) in styles.items():
                group = sorted((row for row in rows if row["condition"] == condition and row["prompt_tokens"] == length),
                               key=lambda row: row["concurrency"])
                if not group:
                    continue
                axis.errorbar([row["concurrency"] for row in group],
                              [row[f"{metric}_mean"] for row in group],
                              yerr=[row[f"{metric}_std"] for row in group],
                              color=color, label=name, marker="o", linewidth=1.8, capsize=3,
                              linestyle="--" if condition in {"base", "cold"} else "-")
            axis.set_title(f"{length} input tokens", loc="left", weight="bold")
            axis.set_xlabel("Concurrent requests")
            axis.set_ylabel(label)
            axis.set_xticks(metadata["concurrencies"])
            axis.grid(alpha=0.18)
            axis.spines[["top", "right"]].set_visible(False)
            if column:
                axis.set_yscale("log")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.94), ncol=3, frameon=False)
    fig.suptitle(f"{metadata['model_id']} | {metadata['gpu']} | {metadata['dtype']}", y=0.99, weight="bold")
    fig.text(0.5, 0.01, f"{metadata['max_tokens']} output tokens; {metadata['repetitions']} repetitions x "
             f"{metadata['waves']} waves. Mean with sample SD. Queueing included; HTTP excluded.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.04, 1, 0.87))
    output = args.report_dir / "figures/benchmark-comparison.png"
    output.parent.mkdir(exist_ok=True)
    fig.savefig(output, dpi=180, facecolor="white")
    print(output)


if __name__ == "__main__":
    main()
