#!/usr/bin/env python3
"""Evaluate generated MMLU choices through the chat API. Standard library only."""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "benchmarks/inference.json").read_text())
DATA_URL = "https://people.eecs.berkeley.edu/~hendrycks/data.tar"
LETTERS = "ABCD"


def download_data(destination, timeout):
    if destination.exists():
        raise ValueError(f"Refusing to replace existing dataset: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Copy only recognized CSV members, without extracting archive paths or links.
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix="mmlu-") as directory:
        staging = Path(directory) / "data"
        with urllib.request.urlopen(DATA_URL, timeout=timeout) as response:
            with tarfile.open(fileobj=response, mode="r|*") as archive:
                for member in archive:
                    match = re.fullmatch(r"(?:\./)?data/(test|dev)/([a-z0-9_]+)_(test|dev)\.csv",
                                         member.name)
                    if not match or not member.isfile() or match[1] != match[3]:
                        continue
                    target = staging / match[1] / f"{match[2]}_{match[3]}.csv"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
        if not (staging / "test").is_dir() or not (staging / "dev").is_dir():
            raise ValueError("MMLU archive is missing test or dev CSV files")
        staging.rename(destination)


def read_questions(path):
    questions = []
    with path.open(encoding="utf-8", newline="") as source:
        for index, row in enumerate(csv.reader(source, strict=True)):
            if (len(row) != 6 or not all(cell.strip() for cell in row[:5])
                    or row[5].strip() not in tuple(LETTERS)):
                raise ValueError(f"Invalid MMLU row {index + 1} in {path}: expected question, A, B, C, D, answer")
            questions.append({"index": index, "question": row[0], "choices": row[1:5],
                              "expected": row[5].strip()})
    if not questions:
        raise ValueError(f"Empty MMLU CSV: {path}")
    return questions


def load_dataset(args):
    available = {path.name.removesuffix("_test.csv")
                 for path in (args.data_dir / "test").glob("*_test.csv")}
    if not available:
        raise ValueError(f"No test CSV files in {args.data_dir}/test; use --download-data or --data-dir")
    subjects = sorted(set(args.subjects or available))
    if unknown := set(subjects) - available:
        raise ValueError(f"Unknown subjects: {', '.join(sorted(unknown))}")
    dataset, hashes = {}, {}
    for subject in subjects:
        examples = []
        for split in (["test", "dev"] if args.few_shot else ["test"]):
            path = args.data_dir / split / f"{subject}_{split}.csv"
            rows = read_questions(path)
            hashes[f"{split}/{path.name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
            if split == "test":
                questions = rows
            else:
                if len(rows) < args.few_shot:
                    raise ValueError(f"{subject} has fewer than {args.few_shot} dev examples")
                examples = rows[:args.few_shot]
        if args.limit and len(questions) > args.limit:
            # A separate seed per subject keeps selections stable when filtering subjects.
            questions = sorted(random.Random(f"{args.seed}:{subject}").sample(questions, args.limit),
                               key=lambda question: question["index"])
        dataset[subject] = (questions, examples)
    return dataset, hashes


def format_question(question, answered=False):
    lines = [question["question"]]
    lines.extend(f"{letter}. {text}" for letter, text in zip(LETTERS, question["choices"]))
    lines.append("Answer:" + (f" {question['expected']}" if answered else ""))
    return "\n".join(lines)


def make_prompt(subject, question, examples):
    sections = [f"Answer the multiple choice question about {subject.replace('_', ' ')}. "
                "Reply with only one letter: A, B, C, or D."]
    sections.extend(format_question(example, answered=True) for example in examples)
    sections.append(format_question(question))
    return "\n\n".join(sections)


def parse_answer(answer):
    match = re.fullmatch(r"(?:Answer:\s*)?([ABCD])[.)]?", answer.strip())
    return match[1] if match else None


def check_question(args, subject, question, examples):
    prompt = make_prompt(subject, question, examples)
    payload = {"model": args.model, "messages": [{"role": "user", "content": prompt}],
               "max_completion_tokens": args.max_tokens, "temperature": 0, "top_p": 1,
               "ignore_eos": False, "stream": False}
    result = {"subject": subject, **question, "prompt": prompt, "prediction": None,
              "correct": False, "status": "ERROR"}
    started = time.monotonic()
    try:
        request = urllib.request.Request(
            args.url + "/v1/chat/completions", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            body = json.load(response)
        result["response"] = body
        if not isinstance(body, dict) or body.get("error"):
            raise ValueError("API returned an error or a non-object response")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("API response has no choices[0] object")
        choice = choices[0]
        message = choice.get("message")
        answer = message.get("content") if isinstance(message, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("API returned an empty or non-text answer")
        result.update(answer=answer, finish_reason=choice.get("finish_reason"))
        if result["finish_reason"] != "stop":
            raise ValueError(f"Incomplete response: finish_reason={result['finish_reason']!r}")
        prediction = parse_answer(answer)
        correct = prediction == question["expected"]
        result.update(prediction=prediction, correct=correct,
                      status="INVALID" if prediction is None else "CORRECT" if correct else "INCORRECT")
    except urllib.error.HTTPError as error:
        result["error"] = f"HTTP {error.code}: " + error.read(4096).decode("utf-8", errors="replace")
    except (OSError, ValueError, http.client.HTTPException) as error:
        result["error"] = str(error)
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def summarize(results):
    counts = Counter(result["status"] for result in results)
    return {"total": len(results), "correct": counts["CORRECT"], "incorrect": counts["INCORRECT"],
            "invalid": counts["INVALID"], "errors": counts["ERROR"],
            "accuracy": counts["CORRECT"] / len(results) if results else None}


def parse_args(argv=None, parser=None, default_url="http://127.0.0.1:8000"):
    parser = parser or argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=tuple(CATALOG), default="transformers",
                        help="Default model and report directory, from benchmarks/inference.json")
    parser.add_argument("--url", default=os.environ.get("API_SERVER_URL", default_url),
                        help="Server base URL, without /v1/chat/completions")
    parser.add_argument("--model", default=os.environ.get("SERVED_MODEL_NAME"))
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".datasets/mmlu",
                        help="Directory containing test/ and dev/ in the original MMLU CSV format")
    parser.add_argument("--download-data", action="store_true", help="Download official data if the directory is absent")
    parser.add_argument("--subjects", nargs="+", help="Subject names; defaults to all available subjects")
    parser.add_argument("--few-shot", type=int, default=0, help="Number of dev examples per prompt (0 to 5)")
    parser.add_argument("--limit", type=int, help="Maximum sampled test questions per subject; defaults to all")
    parser.add_argument("--seed", type=int, default=0, help="Seed for reproducible per-subject sampling")
    parser.add_argument("--max-tokens", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=60, help="Timeout per HTTP request in seconds")
    parser.add_argument("--min-accuracy", type=float, help="Fail below this overall accuracy (0 to 1)")
    parser.add_argument("--output", type=Path, help="JSON report path; see the MMLU guide for default locations")
    args = parser.parse_args(argv)
    args.model = args.model or CATALOG[args.backend]["model"]
    args.url = args.url.rstrip("/")
    parsed = urllib.parse.urlsplit(args.url)
    if (args.url or default_url) and (parsed.scheme not in {"http", "https"} or not parsed.netloc
                                     or parsed.query or parsed.fragment):
        parser.error("--url must be an HTTP(S) base URL without a query or fragment")
    if not 0 <= args.few_shot <= 5:
        parser.error("--few-shot must be between 0 and 5")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.max_tokens < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--max-tokens and --timeout must be positive and finite")
    if args.min_accuracy is not None and not 0 <= args.min_accuracy <= 1:
        parser.error("--min-accuracy must be between 0 and 1")
    if args.output and args.output.suffix.lower() != ".json":
        parser.error("--output must end in .json (a sibling .jsonl stores completed answers)")
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.download_data and not args.data_dir.exists():
        print(f"Downloading MMLU from {DATA_URL}", flush=True)
        download_data(args.data_dir, args.timeout)
    dataset, hashes = load_dataset(args)
    now = datetime.now(timezone.utc)
    output = args.output or Path("docs/reports") / args.backend / f"mmlu-{now:%Y%m%d-%H%M%S-%f}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    results = []
    interrupted = False
    # Flush each completed answer so an interrupted long run retains its evidence.
    with output.with_suffix(".jsonl").open("w", encoding="utf-8") as journal:
        try:
            for subject, (questions, examples) in dataset.items():
                for question in questions:
                    result = check_question(args, subject, question, examples)
                    results.append(result)
                    journal.write(json.dumps(result, ensure_ascii=False) + "\n")
                    journal.flush()
                    print(f"{subject}:{question['index']} {result['status']}", flush=True)
        except KeyboardInterrupt:
            interrupted = True
    summary = summarize(results)
    passed = (not interrupted and not summary["errors"] and
              (args.min_accuracy is None or summary["accuracy"] >= args.min_accuracy))
    report = {
        "suite": "mmlu", "scoring": "generated-choice-v1", "backend": args.backend,
        "model": args.model, "url": args.url, "started_at": now.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "complete": not interrupted, "passed": passed,
        "dataset": {"directory": str(args.data_dir.resolve()), "file_sha256": hashes,
                    "subjects": list(dataset), "split": "test", "few_shot_split": "dev",
                    "planned_questions": sum(len(questions) for questions, _ in dataset.values())},
        "settings": {"few_shot": args.few_shot, "limit_per_subject": args.limit, "seed": args.seed,
                     "max_tokens": args.max_tokens, "temperature": 0, "top_p": 1, "ignore_eos": False,
                     "timeout_seconds": args.timeout, "min_accuracy": args.min_accuracy},
        "summary": summary,
        "per_subject": {subject: summarize([result for result in results if result["subject"] == subject])
                        for subject in dataset},
        "results": results,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    accuracy = f"{summary['accuracy']:.2%}" if summary["accuracy"] is not None else "n/a"
    print(f"Accuracy: {accuracy} ({summary['correct']}/{summary['total']}), "
          f"invalid: {summary['invalid']}, errors: {summary['errors']}")
    print(f"Report: {output}")
    return 130 if interrupted else 0 if passed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, csv.Error, tarfile.TarError, http.client.HTTPException) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
