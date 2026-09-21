"""Exercise the quality CLI against a local chat API with controlled responses."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check-quality.py"


def chat(answer, finish_reason="stop"):
    return {"choices": [{"message": {"role": "assistant", "content": answer},
                         "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50}}


def answers():
    return [chat("PASS\n"), chat("42"), chat("ZX-2048"),
            chat('{"count": 3, "name": "Mina"}'), chat("모카"),
            chat("도서관은 월요일 시설 점검으로 휴관하고 화요일 오전 9시에 다시 엽니다."),
            chat("회의는 오후 3시에 시작합니다.")]


class QualityCheckTests(unittest.TestCase):
    def run_check(self, replies, model="test-model", language=None, backend="transformers", default_output=False):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                index = len(received)
                received.append((self.path, body))
                reply = replies[index]
                status, body = reply if isinstance(reply, tuple) else (200, reply)
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
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
                output = Path(directory) / "nested/quality.json"
                env = {**os.environ, "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}
                env.pop("SERVED_MODEL_NAME", None)
                process = subprocess.run(
                    [sys.executable, str(SCRIPT), "--url", f"http://127.0.0.1:{server.server_port}",
                     "--backend", backend, "--timeout", "2"]
                    + (["--model", model] if model else [])
                    + (["--output", str(output)] if not default_output else [])
                    + (["--language", language] if language else []),
                    text=True, capture_output=True, timeout=15, env=env, cwd=directory,
                )
                if default_output:
                    outputs = list((Path(directory) / "reports" / backend).glob("quality-*.json"))
                    self.assertEqual(len(outputs), 1, process.stderr)
                    output = outputs[0]
                self.assertTrue(output.is_file(), process.stderr)
                report = json.loads(output.read_text())
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
        return process, report, received

    def test_backend_routes_default_model_and_output_directory(self):
        for backend, model in [("transformers", "HuggingFaceTB/SmolLM2-135M-Instruct"),
                               ("llamacpp", "Qwen/Qwen2.5-0.5B-Instruct")]:
            with self.subTest(backend=backend):
                process, report, received = self.run_check(
                    answers(), model=None, language="ko", backend=backend, default_output=True)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(report["backend"], backend)
                self.assertTrue(all(body["model"] == model for _, body in received))

    def test_correct_answers_keep_subjective_cases_for_review(self):
        process, report, received = self.run_check(answers())
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(report["summary"], {"PASS": 5, "FAIL": 0, "REVIEW": 2, "ERROR": 0})
        self.assertEqual(report["automatic_cases"], 5)
        self.assertEqual(len(received), 7)
        for path, body in received:
            self.assertEqual(path, "/v1/chat/completions")
            self.assertEqual(body["model"], "test-model")
            self.assertEqual(body["temperature"], 0)
            self.assertFalse(body["ignore_eos"])
            self.assertFalse(body["stream"])
            self.assertEqual(body["max_completion_tokens"], 128)
        self.assertEqual([message["role"] for message in received[4][1]["messages"]],
                         ["user", "assistant", "user"])
        self.assertIn("화요일", report["results"][5]["answer"])
        self.assertIn("usage", report["results"][0]["response"])

    def test_correct_content_passes_with_explanations_and_code_fences(self):
        replies = answers()
        replies[0] = chat("답은 **PASS**입니다.")
        replies[1] = chat("17 + 25 = 42")
        replies[2] = chat("ZX-2048입니다. 배송일은 금요일입니다.")
        replies[3] = chat('다음과 같습니다.\n```json\n{"name": "Mina", "count": "3", "note": "ok"}\n```')
        replies[4] = chat("고양이 이름은 모카입니다.")
        process, report, _ = self.run_check(replies)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(report["summary"], {"PASS": 5, "FAIL": 0, "REVIEW": 2, "ERROR": 0})
        self.assertEqual(report["rubric"], "content-v1")

    def test_wrong_content_does_not_pass(self):
        replies = answers()
        replies[0] = chat("BYPASS")
        replies[1] = chat("정답은 142입니다.")
        replies[2] = chat("주문번호는 ZX-20480입니다.")
        replies[3] = chat('```json\n{"name": "Mina", "count": 4}\n```')
        replies[4] = chat("고양이 이름은 모카라떼입니다.")
        process, report, _ = self.run_check(replies)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(report["summary"], {"PASS": 0, "FAIL": 5, "REVIEW": 2, "ERROR": 0})

    def test_ambiguous_content_and_unparsed_fields_need_review(self):
        replies = answers()
        replies[0] = chat("Do not output PASS")
        replies[1] = chat("42 또는 43입니다.")
        replies[2] = chat("ZX-2048과 ZX-2049입니다.")
        replies[3] = chat("이름은 Mina이고 개수는 3입니다.")
        replies[4] = chat("고양이 이름은 모카가 아닙니다.")
        process, report, _ = self.run_check(replies)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(report["summary"], {"PASS": 0, "FAIL": 0, "REVIEW": 7, "ERROR": 0})

    def test_errors_and_truncated_answers_are_saved_and_remaining_cases_run(self):
        replies = answers()
        replies[0] = (503, {"error": {"message": "model unavailable"}})
        replies[1] = chat("42", "length")
        replies[2] = chat(" ")
        replies[3] = {"choices": []}
        replies[4] = {"error": {"message": "generation failed"}}
        process, report, received = self.run_check(replies)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(len(received), 7)
        self.assertEqual(report["summary"], {"PASS": 0, "FAIL": 0, "REVIEW": 2, "ERROR": 5})
        self.assertIn("503", report["results"][0]["reason"])
        self.assertEqual(report["results"][1]["answer"], "42")
        self.assertEqual(report["results"][1]["finish_reason"], "length")

    def test_smollm2_selects_english_and_checks_name_boundaries(self):
        replies = answers()
        replies[4] = chat("Your cat's name is Mocha.")
        replies[5] = chat("The library closes on Monday for maintenance and reopens Tuesday at 9 a.m.")
        replies[6] = chat("The meeting starts at 3 p.m.")
        process, report, received = self.run_check(replies, model="HuggingFaceTB/SmolLM2-135M-Instruct")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(report["summary"], {"PASS": 5, "FAIL": 0, "REVIEW": 2, "ERROR": 0})
        self.assertEqual(report["language"], "en")
        self.assertEqual(report["suite"], "basic-en-v1")
        self.assertIn("Calculate 17 + 25", received[1][1]["messages"][0]["content"])
        self.assertEqual(report["results"][-1]["id"], "paraphrase")
        replies[4] = chat("Your cat's name is Mochaccino.")
        _, report, _ = self.run_check(replies, model="local-smollm2")
        self.assertEqual(report["results"][4]["status"], "FAIL")

    def test_explicit_language_overrides_model_detection(self):
        process, report, _ = self.run_check(answers(), model="SmolLM2", language="ko")
        self.assertEqual(process.returncode, 0)
        self.assertEqual(report["language"], "ko")
        self.assertEqual(report["suite"], "basic-ko-v1")
        self.assertEqual(report["results"][-1]["id"], "translation")


if __name__ == "__main__":
    unittest.main()
