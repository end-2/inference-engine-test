"""Smoke test for the base-llamacpp chat API. Standard library only."""

import json
import os
import sys
import urllib.request

BASE_URL = os.environ.get("API_SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
MODEL = os.environ.get("SERVED_MODEL_NAME", "Qwen/Qwen2.5-0.5B-Instruct")


def get(path):
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=30) as response:
        return response.status, json.load(response)


def post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.status, json.load(response)


def post_stream(path, payload):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, headers={"Content-Type": "application/json"}
    )
    frames = []
    with urllib.request.urlopen(request, timeout=300) as response:
        for line in response:
            text = line.decode("utf-8").strip()
            if text.startswith("data:"):
                frames.append(text[len("data:"):].strip())
    return frames


def check(name, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}: {name} {detail}".rstrip())
    if not condition:
        raise SystemExit(1)


def main():
    status, body = get("/healthz")
    check("healthz", status == 200 and body.get("status") == "ok", str(body))

    status, body = get("/readyz")
    check("readyz", status == 200 and body.get("status") == "ready", str(body))

    status, body = get("/v1/models")
    ids = [item.get("id") for item in body.get("data", [])]
    check("models", status == 200 and MODEL in ids, str(ids))

    status, body = post(
        "/v1/chat/completions",
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": "Say hello in one short sentence."}],
            "max_completion_tokens": 32,
        },
    )
    choice = (body.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content", "")
    check("chat", status == 200 and bool(content.strip()), repr(content[:80]))

    frames = post_stream(
        "/v1/chat/completions",
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": "Say hello in one short sentence."}],
            "max_completion_tokens": 32,
            "stream": True,
            "stream_options": {"include_usage": True},
        },
    )
    check("stream frames", frames and frames[-1] == "[DONE]", f"{len(frames)} frames")
    chunks = [json.loads(frame) for frame in frames[:-1]]
    check("stream errors", not any("error" in chunk for chunk in chunks))
    content = "".join(
        choice.get("delta", {}).get("content", "")
        for chunk in chunks for choice in chunk.get("choices", [])
    )
    check("stream content", bool(content.strip()), repr(content[:80]))
    check("stream finish", any(
        choice.get("finish_reason") in {"stop", "length"}
        for chunk in chunks for choice in chunk.get("choices", [])
    ))
    counts = chunks[-1].get("usage", {})
    check("stream usage", counts.get("prompt_tokens", 0) > 0
          and counts.get("completion_tokens", 0) > 0
          and counts.get("total_tokens") == counts.get("prompt_tokens", 0)
          + counts.get("completion_tokens", 0), str(counts))
    print("All smoke checks passed.")


if __name__ == "__main__":
    sys.exit(main())
