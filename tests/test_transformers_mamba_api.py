"""Compare running Mamba base and checkpoint servers through HTTP and SSE."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
import unittest
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("TEST_MAMBA_BASE_URL")
CACHE_URL = os.environ.get("TEST_MAMBA_CACHE_URL")


@unittest.skipUnless(BASE_URL and CACHE_URL, "Set TEST_MAMBA_BASE_URL and TEST_MAMBA_CACHE_URL")
class MambaAPITests(unittest.TestCase):
    def body(self, text=None, **options):
        return {"model": "state-spaces/mamba-130m-hf", "messages": [{"role": "user", "content": text or (
            "The river flows through the forest. People study the water and the trees. " * 4)}],
                "max_tokens": 8, "temperature": 0, "ignore_eos": True, **options}

    def request(self, url, body):
        request = Request(url + "/v1/chat/completions", json.dumps(body).encode(),
                          {"Content-Type": "application/json"})
        with urlopen(request, timeout=90) as response:
            return response.read().decode()

    def completion(self, url, body):
        result = json.loads(self.request(url, body))
        return result["choices"][0]["message"]["content"], result["choices"][0]["finish_reason"], result["usage"]

    def test_health_model_and_repeated_output(self):
        for url in (BASE_URL, CACHE_URL):
            with urlopen(url + "/readyz", timeout=30) as response:
                self.assertEqual(response.status, 200)
            with urlopen(url + "/v1/models", timeout=30) as response:
                self.assertEqual(json.load(response)["data"][0]["id"], "state-spaces/mamba-130m-hf")
        expected = self.completion(BASE_URL, self.body())
        for _ in range(2):
            self.assertEqual(self.completion(CACHE_URL, self.body()), expected)
        self.assertEqual(expected[2]["completion_tokens"], 8)

    def test_stream_matches_completion_and_usage(self):
        expected = self.completion(BASE_URL, self.body())
        for _ in range(2):
            data = self.request(CACHE_URL, self.body(stream=True, stream_options={"include_usage": True}))
            frames = [line[6:] for line in data.splitlines() if line.startswith("data: ")]
            self.assertEqual(frames[-1], "[DONE]")
            events = [json.loads(frame) for frame in frames[:-1]]
            text = "".join(choice["delta"].get("content", "") for event in events for choice in event.get("choices", []))
            self.assertEqual(text, expected[0])
            self.assertEqual(events[-1]["usage"], expected[2])

    def test_concurrent_and_divergent_prompts_are_isolated(self):
        texts = [("A traveler studies the forest and the river. " * 5) + ending
                 for ending in ("The first discovery was", "The second discovery was", "The next day", "At night")]
        bodies = [self.body(text) for text in texts]
        expected = [self.completion(BASE_URL, body) for body in bodies]
        with ThreadPoolExecutor(max_workers=4) as pool:
            actual = list(pool.map(lambda body: self.completion(CACHE_URL, body), bodies))
        self.assertEqual(actual, expected)

    def test_multiturn_and_eos_enabled_match_base(self):
        body = self.body(ignore_eos=False, messages=[
            {"role": "system", "content": "Continue the story."},
            {"role": "user", "content": "The traveler reached the river."},
            {"role": "assistant", "content": "A boat was waiting."},
            {"role": "user", "content": "What happened next?"},
        ])
        self.assertEqual(self.completion(CACHE_URL, body), self.completion(BASE_URL, body))


if __name__ == "__main__":
    unittest.main()
