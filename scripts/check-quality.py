#!/usr/bin/env python3
"""Check basic chat answers and save responses for manual review. Standard library only."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request


KOREAN_CASES = (
    {
        "id": "instruction",
        "messages": [{"role": "user", "content": "다른 설명 없이 PASS라는 단어만 출력하세요."}],
        "expected": "PASS",
        "criterion": "PASS라는 답을 제시하는지 확인, 설명과 서식은 허용",
    },
    {
        "id": "arithmetic",
        "messages": [{"role": "user", "content": "17 + 25를 계산하세요. 정답 숫자만 출력하세요."}],
        "expected": "42",
        "criterion": "계산 결과가 42인지 확인, 수식과 설명은 허용",
    },
    {
        "id": "extraction",
        "messages": [{"role": "user", "content": (
            "문장: 주문번호는 ZX-2048이고 배송일은 금요일입니다. "
            "주문번호만 그대로 출력하세요. 다른 설명은 쓰지 마세요."
        )}],
        "expected": "ZX-2048",
        "criterion": "주문번호 ZX-2048을 정확하게 제시하는지 확인, 설명은 허용",
    },
    {
        "id": "json",
        "messages": [{"role": "user", "content": (
            'name 값이 "Mina"이고 count 값이 숫자 3인 JSON 객체를 출력하세요. '
            "이 두 필드만 포함하고 설명이나 코드 블록은 쓰지 마세요."
        )}],
        "expected": {"name": "Mina", "count": 3},
        "criterion": 'name이 Mina이고 count가 3인지 확인, 설명과 코드 블록 및 추가 필드는 허용',
    },
    {
        "id": "conversation",
        "messages": [
            {"role": "user", "content": "내 고양이 이름은 모카입니다."},
            {"role": "assistant", "content": "고양이 이름이 모카군요."},
            {"role": "user", "content": "내 고양이 이름만 출력하세요. 다른 설명은 쓰지 마세요."},
        ],
        "expected": "모카",
        "criterion": "대화에서 제시한 이름 모카를 답하는지 확인, 설명은 허용",
    },
    {
        "id": "summary",
        "messages": [{"role": "user", "content": (
            "다음 내용을 한국어 한 문장으로 요약하세요. "
            "도서관은 시설 점검 때문에 월요일에 문을 닫습니다. 화요일 오전 9시에 다시 엽니다."
        )}],
        "criterion": "월요일 시설 점검으로 휴관하고 화요일 오전 9시에 재개한다는 사실을 보존",
    },
    {
        "id": "translation",
        "messages": [{"role": "user", "content": (
            "다음 문장을 한국어로 번역하세요. 번역문만 출력하세요. "
            "The meeting starts at three in the afternoon."
        )}],
        "criterion": "회의가 오후 3시에 시작한다는 의미를 보존하는 자연스러운 한국어 번역",
    },
)


ENGLISH_CASES = (
    {
        "id": "instruction",
        "messages": [{"role": "user", "content": "Output only the word PASS, without any explanation."}],
        "expected": "PASS",
        "criterion": "PASS라는 답을 제시하는지 확인, 설명과 서식은 허용",
    },
    {
        "id": "arithmetic",
        "messages": [{"role": "user", "content": "Calculate 17 + 25. Output only the answer as a number."}],
        "expected": "42",
        "criterion": "계산 결과가 42인지 확인, 수식과 설명은 허용",
    },
    {
        "id": "extraction",
        "messages": [{"role": "user", "content": (
            "The order number is ZX-2048 and delivery is on Friday. "
            "Output only the order number, exactly as written."
        )}],
        "expected": "ZX-2048",
        "criterion": "주문번호 ZX-2048을 정확하게 제시하는지 확인, 설명은 허용",
    },
    {
        "id": "json",
        "messages": [{"role": "user", "content": (
            'Output a JSON object with "name" set to "Mina" and "count" set to the number 3. '
            "Include only these two fields, without explanations or code fences."
        )}],
        "expected": {"name": "Mina", "count": 3},
        "criterion": 'name이 Mina이고 count가 3인지 확인, 설명과 코드 블록 및 추가 필드는 허용',
    },
    {
        "id": "conversation",
        "messages": [
            {"role": "user", "content": "My cat's name is Mocha."},
            {"role": "assistant", "content": "Your cat's name is Mocha."},
            {"role": "user", "content": "What is my cat's name? Output only the name."},
        ],
        "expected": "Mocha",
        "criterion": "대화에서 제시한 이름 Mocha를 답하는지 확인, 설명은 허용",
    },
    {
        "id": "summary",
        "messages": [{"role": "user", "content": (
            "Summarize this in one English sentence: The library is closed on Monday "
            "for maintenance. It reopens on Tuesday at 9 a.m."
        )}],
        "criterion": "월요일 시설 점검으로 휴관하고 화요일 오전 9시에 재개한다는 사실을 보존",
    },
    {
        "id": "paraphrase",
        "messages": [{"role": "user", "content": (
            "Rewrite this sentence in simpler English, keeping its meaning: "
            "The meeting will commence at three o'clock in the afternoon."
        )}],
        "criterion": "회의가 오후 3시에 시작한다는 의미를 보존하는 자연스러운 영어 문장",
    },
)


RUBRIC = "content-v1"


def judge(case, answer):
    if "expected" not in case:
        return "REVIEW", "응답과 기준을 사람이 비교해야 합니다."
    answer = unicodedata.normalize("NFC", answer.strip())
    expected = case["expected"]
    # A token match cannot resolve negation, alternatives, or quoted examples.
    if re.search(r"아니|아닙|않|틀|예시|또는|혹은|\b(?:not|never|wrong|incorrect|or|example)\b",
                 answer, re.IGNORECASE):
        return "REVIEW", "부정이나 대안 표현이 있어 정답으로 제시한 내용을 확인해야 합니다."
    if isinstance(expected, dict):
        decoder = json.JSONDecoder()
        objects = []
        offset = 0
        while (start := answer.find("{", offset)) >= 0:
            try:
                actual, length = decoder.raw_decode(answer[start:])
            except ValueError:
                offset = start + 1
                continue
            objects.append(actual)
            offset = start + length
        if len(objects) != 1 or not all(key in objects[0] for key in expected):
            return "REVIEW", "응답에서 name과 count의 내용을 확인해야 합니다. 출력 형식은 평가하지 않습니다."
        actual = objects[0]
        matches = actual["name"] == expected["name"] and str(actual["count"]).strip() in {"3", "3.0"}
    elif case["id"] == "arithmetic":
        numbers = [float(value.replace(",", ""))
                   for value in re.findall(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?", answer)]
        if 42 in numbers and (numbers[-1] != 42 or any(n not in {17, 25, 42} for n in numbers)):
            return "REVIEW", "계산 결과와 다른 숫자가 함께 있어 최종 답을 확인해야 합니다."
        matches = bool(numbers) and numbers[-1] == 42
    else:
        if case["id"] == "conversation" and expected == "모카":
            pattern = r"(?<!\w)모카(?=$|[^\w]|(?:입니다|이에요|예요|라고|라는|[이가은는을를])(?:$|[^\w]))"
        else:
            pattern = rf"(?<![A-Za-z0-9_-]){re.escape(expected)}(?![A-Za-z0-9_-])"
        matches = re.search(pattern, answer) is not None
        if case["id"] == "extraction" and matches:
            codes = set(re.findall(r"[A-Za-z]+-\d+", answer))
            if codes != {expected}:
                return "REVIEW", "서로 다른 주문번호가 있어 최종 답을 확인해야 합니다."
    if matches:
        return "PASS", "정답 내용과 일치합니다. 설명과 출력 형식은 평가하지 않습니다."
    return "FAIL", "정답 내용과 일치하지 않습니다."


def check_case(case, url, model, max_tokens, timeout):
    payload = {
        "model": model,
        "messages": case["messages"],
        "temperature": 0,
        "top_p": 1,
        "max_completion_tokens": max_tokens,
        "stream": False,
        "ignore_eos": False,
    }
    result = {**case, "automatic": "expected" in case, "request": payload}
    started = time.monotonic()
    try:
        request = urllib.request.Request(
            url + "/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.load(response)
        result["response"] = body
        if not isinstance(body, dict) or body.get("error"):
            raise ValueError("API가 정상 채팅 응답을 반환하지 않았습니다.")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("API 응답에 choices[0] 객체가 없습니다.")
        choice = choices[0]
        message = choice.get("message")
        answer = message.get("content") if isinstance(message, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("API가 비어 있거나 문자열이 아닌 응답을 반환했습니다.")
        result["answer"] = answer
        result["finish_reason"] = choice.get("finish_reason")
        if result["finish_reason"] == "length":
            raise ValueError("출력 토큰 상한에 도달했습니다. 상한을 늘려 다시 확인하세요.")
        if result["finish_reason"] != "stop":
            raise ValueError(f"정상 완료 여부를 확인할 수 없습니다: {result['finish_reason']!r}")
        result["status"], result["reason"] = judge(case, answer)
    except urllib.error.HTTPError as error:
        result.update(status="ERROR", reason=f"HTTP {error.code}: " +
                      error.read(4096).decode("utf-8", errors="replace"))
    except (OSError, ValueError) as error:
        result.update(status="ERROR", reason=str(error))
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("llamacpp", "transformers"), default="transformers",
                        help="Select the default model and report directory")
    parser.add_argument("--url", default=os.environ.get("API_SERVER_URL", "http://127.0.0.1:8000"),
                        help="API base URL, without /v1/chat/completions")
    parser.add_argument("--model", default=os.environ.get("SERVED_MODEL_NAME"))
    parser.add_argument("--language", choices=("auto", "en", "ko"), default="auto",
                        help="auto selects English for SmolLM2, Korean for other models")
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--timeout", type=float, default=60, help="Timeout per request in seconds")
    parser.add_argument("--output", type=Path, help="JSON report path; defaults to reports/<backend>/quality-<UTC>.json")
    args = parser.parse_args(argv)
    args.model = args.model or ("HuggingFaceTB/SmolLM2-135M-Instruct" if args.backend == "transformers"
                                else "Qwen/Qwen2.5-0.5B-Instruct")
    if args.language == "auto":
        args.language = "en" if "smollm2" in args.model.lower() else "ko"
    args.url = args.url.rstrip("/")
    parsed = urllib.parse.urlsplit(args.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
        parser.error("--url must be an HTTP(S) base URL without a query or fragment")
    if args.max_tokens < 1 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--max-tokens and --timeout must be positive and finite")
    return args


def main(argv=None):
    args = parse_args(argv)
    now = datetime.now(timezone.utc)
    output = args.output or Path("reports") / args.backend / f"quality-{now:%Y%m%d-%H%M%S-%f}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    results = []
    cases = ENGLISH_CASES if args.language == "en" else KOREAN_CASES
    for case in cases:
        result = check_case(case, args.url, args.model, args.max_tokens, args.timeout)
        results.append(result)
        print(f"{result['status']}: {case['id']} — {result['reason']}", flush=True)
        print(f"  기준: {case['criterion']}")
        if "answer" in result:
            print("  응답: " + result["answer"].replace("\n", "\n        "), flush=True)
    counts = Counter(result["status"] for result in results)
    summary = {status: counts[status] for status in ("PASS", "FAIL", "REVIEW", "ERROR")}
    report = {
        "backend": args.backend,
        "started_at": now.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "url": args.url,
        "model": args.model,
        "max_tokens": args.max_tokens,
        "timeout_seconds": args.timeout,
        "rubric": RUBRIC,
        "language": args.language,
        "suite": f"basic-{args.language}-v1",
        "automatic_cases": sum(result["automatic"] for result in results),
        "summary": summary,
        "results": results,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"자동 통과 {counts['PASS']}/{report['automatic_cases']}, 실패 {counts['FAIL']}, "
          f"수동 확인 {counts['REVIEW']}, 오류 {counts['ERROR']}")
    print(f"결과: {output}")
    return 1 if counts["FAIL"] or counts["ERROR"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except OSError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
