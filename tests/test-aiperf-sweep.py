"""Run the manifest's native sweep against a local SSE server, without external network."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

import yaml

ROOT = Path(__file__).resolve().parents[1]


class ChatHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["stream"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        metadata = {"id": "chatcmpl-test", "object": "chat.completion.chunk",
                    "created": 0, "model": body["model"]}
        for delta, finish in [({"role": "assistant"}, None),
                              ({"content": "hello"}, None), ({}, "length")]:
            chunk = {**metadata, "choices": [
                {"index": 0, "delta": delta, "finish_reason": finish}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        chunk = {**metadata, "choices": [], "usage": {
            "prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}}
        self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())


def main():
    tokenizer = Path(os.environ.get(
        "TEST_TOKENIZER_PATH", ROOT / ".models/qwen2.5-0.5b/tokenizer")).resolve()
    if not tokenizer.is_dir():
        raise SystemExit("Run ./scripts/download-tokenizer.sh first, or set TEST_TOKENIZER_PATH.")
    job = yaml.safe_load((ROOT / "k8s/aiperf/job.yaml").read_text())
    container = job["spec"]["template"]["spec"]["containers"][0]
    values = {item["name"]: item["value"] for item in container["env"] if "value" in item}
    server = ThreadingHTTPServer(("127.0.0.1", 0), ChatHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryDirectory(prefix="aiperf-sweep-test-") as directory:
            work = Path(directory)
            values.update(API_URL=f"http://127.0.0.1:{server.server_port}", POD_NAME="smoke")
            args = list(container["args"])
            for index, argument in enumerate(args):
                for name, value in values.items():
                    argument = argument.replace(f"$({name})", value)
                args[index] = argument
            for option, value in {
                "--tokenizer": str(tokenizer), "--artifact-dir": str(work / "results"),
                "--sequence-distribution": "8,4:100", "--num-dataset-entries": "8",
                "--request-count": "8", "--warmup-request-count": "1",
                "--request-timeout-seconds": "10",
            }.items():
                args[args.index(option) + 1] = value
            # Inherited by AIPerf worker subprocesses; loopback is needed for IPC
            # and the test API. Fresh caches ensure no HF cache is required.
            (work / "sitecustomize.py").write_text('''
import socket
_connect = socket.socket.connect
_resolve = socket.getaddrinfo
_ALLOWED = {"127.0.0.1", "::1", "localhost", None}
def connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in _ALLOWED:
        raise RuntimeError(f"External connection forbidden: {address}")
    return _connect(self, address)
def resolve(host, *args, **kwargs):
    if host not in _ALLOWED:
        raise RuntimeError(f"External DNS forbidden: {host}")
    return _resolve(host, *args, **kwargs)
socket.socket.connect = connect
socket.getaddrinfo = resolve
''')
            env = {**os.environ, "PYTHONPATH": str(work), "HF_HOME": str(work / "hf"),
                   "HF_HUB_CACHE": str(work / "hf/hub"), "HF_HUB_DISABLE_TELEMETRY": "1",
                   "XDG_CACHE_HOME": str(work / "cache"), "MPLCONFIGDIR": str(work / "mpl"),
                   "TOKENIZERS_PARALLELISM": "false", "OMP_NUM_THREADS": "1",
                   "OPENBLAS_NUM_THREADS": "1", "NO_PROXY": "127.0.0.1,localhost"}
            for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "TRANSFORMERS_CACHE",
                        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
                        "all_proxy"):
                env.pop(key, None)
            with (work / "run.log").open("w+") as log:
                try:
                    subprocess.run([sys.executable, "-m", "aiperf", *args], env=env,
                                   cwd=work, stdout=log, stderr=log, timeout=180, check=True)
                    summary = json.loads((work / "results/sweep_aggregate/profile_export_aiperf_sweep.json").read_text())
                    expected = len(values["CONCURRENCIES"].split(","))
                    assert summary["num_profile_runs"] == expected, summary
                    assert summary["num_successful_runs"] == expected, summary
                    assert not summary["failed_runs"], summary
                except Exception:
                    log.seek(0)
                    print(log.read()[-20000:])
                    raise
                print(f"PASS: {expected} native sweep variations with a local tokenizer and external network blocked")
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


if __name__ == "__main__":
    main()
