"""Verify MMLU scoring, data isolation, and CLI reports without a model or network dataset."""

import csv
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-mmlu.py"
SPEC = importlib.util.spec_from_file_location("mmlu_check", SCRIPT)
mmlu = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mmlu)


def chat(answer, finish_reason="stop"):
    return {"choices": [{"message": {"content": answer}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 2, "total_tokens": 32}}


def write_subject(root, subject, answers, split="test"):
    directory = root / split
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"{subject}_{split}.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        for index, answer in enumerate(answers):
            writer.writerow([f"{split} question {subject} {index}\nwith a comma, here", "one", "two",
                             "three", "four", answer])


class MMLUCheckTests(unittest.TestCase):
    def run_check(self, replies, extra=(), subjects=None, default_output=False):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                index = len(received)
                received.append((self.path, payload))
                reply = replies[index]
                status, body = reply if isinstance(reply, tuple) else (200, reply)
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                data_dir = root / "data"
                for subject, answers in (subjects or {"algebra": ["A", "B", "C"]}).items():
                    write_subject(data_dir, subject, answers)
                    write_subject(data_dir, subject, ["D"] * 5, "dev")
                output = root / "nested/results.json"
                env = {**os.environ, "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}
                env.pop("SERVED_MODEL_NAME", None)
                process = subprocess.run(
                    [sys.executable, str(SCRIPT), "--url", f"http://127.0.0.1:{server.server_port}",
                     "--data-dir", str(data_dir), "--timeout", "2"]
                    + ([] if default_output else ["--output", str(output)]) + list(extra),
                    capture_output=True, text=True, timeout=15, cwd=root, env=env)
                if default_output:
                    outputs = list(root.glob("docs/reports/*/mmlu-*.json"))
                    self.assertEqual(len(outputs), 1, process.stderr)
                    output = outputs[0]
                self.assertTrue(output.exists(), process.stderr)
                report = json.loads(output.read_text())
                journal = [json.loads(line) for line in output.with_suffix(".jsonl").read_text().splitlines()]
                self.assertEqual(journal, report["results"])
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
        return process, report, received

    def test_weighted_accuracy_and_explicit_request_settings(self):
        process, report, received = self.run_check(
            [chat("A"), chat("B."), chat("A"), chat("Answer: D")],
            subjects={"algebra": ["A", "B", "C"], "history": ["D"]})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(report["summary"], {"total": 4, "correct": 3, "incorrect": 1,
                                             "invalid": 0, "errors": 0, "accuracy": .75})
        self.assertEqual(report["per_subject"]["algebra"]["accuracy"], 2 / 3)
        self.assertEqual(report["per_subject"]["history"]["accuracy"], 1)
        self.assertTrue(report["complete"])
        self.assertEqual(len(report["dataset"]["file_sha256"]), 2)
        for path, payload in received:
            self.assertEqual(path, "/v1/chat/completions")
            self.assertEqual(payload["temperature"], 0)
            self.assertEqual(payload["top_p"], 1)
            self.assertFalse(payload["ignore_eos"])
            self.assertFalse(payload["stream"])
            self.assertEqual(payload["max_completion_tokens"], 16)
            prompt = payload["messages"][0]["content"]
            self.assertTrue(prompt.endswith("Answer:"))
            self.assertNotIn("dev question", prompt)

    def test_few_shot_uses_only_selected_subject_dev_rows(self):
        process, report, received = self.run_check(
            [chat("A"), chat("B"), chat("C")], ["--few-shot", "2", "--subjects", "algebra"],
            subjects={"algebra": ["A", "B", "C"], "history": ["D"]})
        self.assertEqual(process.returncode, 0, process.stderr)
        for _, payload in received:
            prompt = payload["messages"][0]["content"]
            self.assertEqual(prompt.count("dev question algebra"), 2)
            self.assertEqual(prompt.count("test question algebra"), 1)
            self.assertEqual(prompt.count("Answer: D"), 2)
            self.assertNotIn("history", prompt)
        self.assertEqual(report["settings"]["few_shot"], 2)
        self.assertEqual(set(report["dataset"]["file_sha256"]),
                         {"test/algebra_test.csv", "dev/algebra_dev.csv"})

    def test_invalid_answers_are_in_denominator_and_threshold_fails(self):
        process, report, _ = self.run_check(
            [chat("A"), chat("B or C"), chat("The answer is C because...")], ["--min-accuracy", ".5"])
        self.assertEqual(process.returncode, 1)
        self.assertEqual(report["summary"]["invalid"], 2)
        self.assertEqual(report["summary"]["accuracy"], 1 / 3)
        self.assertFalse(report["passed"])
        process, report, _ = self.run_check([chat("A"), chat("B"), chat("C")], ["--min-accuracy", "1"])
        self.assertEqual(process.returncode, 0)
        self.assertTrue(report["passed"])

    def test_errors_are_saved_and_remaining_questions_run(self):
        replies = [(503, {"error": "unavailable"}), chat("A", "length"), chat(" "),
                   {"choices": []}, [], chat("D", "content_filter"), chat("A")]
        process, report, received = self.run_check(replies, subjects={"algebra": ["A"] * 7})
        self.assertEqual(process.returncode, 1)
        self.assertEqual(len(received), 7)
        self.assertEqual(report["summary"]["errors"], 6)
        self.assertEqual(report["summary"]["accuracy"], 1 / 7)
        self.assertIn("503", report["results"][0]["error"])
        self.assertEqual(report["results"][1]["answer"], "A")

    def test_backend_defaults_use_catalog(self):
        for backend in mmlu.CATALOG:
            with self.subTest(backend=backend):
                process, report, received = self.run_check(
                    [chat("A")], ["--backend", backend, "--limit", "1"], default_output=True)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(report["backend"], backend)
                self.assertEqual(received[0][1]["model"], mmlu.CATALOG[backend]["model"])

    def test_sampling_is_reproducible_across_subject_filters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_subject(root, "algebra", ["A"] * 40)
            write_subject(root, "history", ["B"] * 40)
            args = mmlu.parse_args(["--data-dir", str(root), "--limit", "7", "--seed", "42"])
            all_data, _ = mmlu.load_dataset(args)
            args.subjects = ["history"]
            filtered, _ = mmlu.load_dataset(args)
            self.assertEqual(all_data["history"], filtered["history"])
            self.assertEqual(len(filtered["history"][0]), 7)
            args.seed = 43
            other, _ = mmlu.load_dataset(args)
            self.assertNotEqual(filtered, other)

    def test_invalid_data_and_missing_dev_fail_before_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_subject(root, "algebra", ["A"])
            args = mmlu.parse_args(["--data-dir", str(root), "--few-shot", "1"])
            with self.assertRaises(FileNotFoundError):
                mmlu.load_dataset(args)
            write_subject(root, "algebra", ["D"], "dev")
            args.few_shot = 5
            with self.assertRaisesRegex(ValueError, "fewer"):
                mmlu.load_dataset(args)
            args.few_shot = 0
            args.subjects = ["unknown"]
            with self.assertRaisesRegex(ValueError, "Unknown subjects"):
                mmlu.load_dataset(args)
            write_subject(root, "bad", ["AB"])
            with self.assertRaises(ValueError):
                mmlu.read_questions(root / "test/bad_test.csv")

    def test_download_copies_only_dataset_csv_and_preserves_existing_data(self):
        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
            for name in ("data/test/algebra_test.csv", "data/dev/algebra_dev.csv",
                         "data/test/../../escape_test.csv", "data/auxiliary_train/algebra_train.csv"):
                content = b"Question,one,two,three,four,A\n"
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            link = tarfile.TarInfo("data/test/link_test.csv")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            archive.addfile(link)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "dataset"
            with patch.object(mmlu.urllib.request, "urlopen", return_value=io.BytesIO(archive_bytes.getvalue())):
                mmlu.download_data(destination, 2)
            self.assertEqual(len(list(destination.rglob("*.csv"))), 2)
            self.assertFalse((Path(directory) / "escape_test.csv").exists())
            with self.assertRaisesRegex(ValueError, "existing dataset"):
                mmlu.download_data(destination, 2)

    def test_interruption_saves_partial_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_subject(root, "algebra", ["A", "B"])
            output = root / "report.json"
            result = {"subject": "algebra", "status": "CORRECT", "correct": True}
            with patch.object(mmlu, "check_question", side_effect=[result, KeyboardInterrupt]):
                code = mmlu.main(["--data-dir", str(root), "--output", str(output)])
            report = json.loads(output.read_text())
            self.assertEqual(code, 130)
            self.assertFalse(report["complete"])
            self.assertFalse(report["passed"])
            self.assertEqual(report["summary"]["total"], 1)
            self.assertEqual(report["dataset"]["planned_questions"], 2)

    def test_invalid_arguments_fail_without_network_access(self):
        for arguments in (["--limit", "0"], ["--few-shot", "6"], ["--timeout", "nan"],
                          ["--max-tokens", "0"], ["--min-accuracy", "nan"],
                          ["--min-accuracy", "1.1"], ["--url", "file:///tmp/data"],
                          ["--output", "answers.jsonl"]):
            with self.subTest(arguments=arguments), patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as error:
                    mmlu.parse_args(arguments)
                self.assertEqual(error.exception.code, 2)

    def test_broken_http_body_is_recorded_as_error(self):
        args = mmlu.parse_args([])
        question = {"index": 0, "question": "Choose one", "choices": list("abcd"), "expected": "A"}
        with patch.object(mmlu.urllib.request, "urlopen", side_effect=mmlu.http.client.IncompleteRead(b"{")):
            result = mmlu.check_question(args, "algebra", question, [])
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("IncompleteRead", result["error"])

    def test_failed_download_leaves_no_partial_dataset(self):
        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w"):
            pass
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "data"
            with patch.object(mmlu.urllib.request, "urlopen", return_value=io.BytesIO(archive_bytes.getvalue())):
                with self.assertRaisesRegex(ValueError, "missing test or dev"):
                    mmlu.download_data(destination, 2)
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
