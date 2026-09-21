"""API regression tests without model weights or a native inference runtime."""

import asyncio
import json
from pathlib import Path
import sys
import threading
import unittest

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from llamacpp.base.server import Settings, create_app


class FakeEngine:
    def __init__(self, settings):
        self.settings = settings
        self.prompt = list(range(8))
        self.messages = None
        self.closed = False
        self.fail = False
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.cancel = None

    def prepare_prompt(self, messages):
        self.messages = messages
        return self.prompt

    def complete(self, prompt, max_tokens, temperature, top_p, ignore_eos, cancel):
        self.calls += 1
        self.cancel = cancel
        self.entered.set()
        if not self.release.wait(5):
            raise RuntimeError("Test worker timed out")
        if self.fail:
            raise RuntimeError("private model error")
        return {"text": "hello", "prompt_tokens": len(prompt),
                "completion_tokens": 3, "finish_reason": "length"}

    def stream(self, *args):
        result = self.complete(*args[:-1])
        args[-1](result["text"])
        return result

    def close(self):
        self.closed = True


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = Settings(n_ctx=32, max_input_tokens=20,
                                 max_output_tokens=16, default_output_tokens=8)
        self.app = create_app(self.settings, FakeEngine)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.engine = self.app.state.engine
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                       base_url="http://test")

    async def asyncTearDown(self):
        self.engine.release.set()
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)
        self.assertTrue(self.engine.closed)

    def payload(self, **kwargs):
        return {"model": self.settings.served_model_name,
                "messages": [{"role": "user", "content": "hello"}], **kwargs}

    async def post(self, **kwargs):
        return await self.client.post("/v1/chat/completions", json=self.payload(**kwargs))

    async def test_usage_and_text_parts(self):
        response = await self.post(messages=[{"role": "user", "content": [
            {"type": "text", "text": "hel"}, {"type": "text", "text": "lo"}]}])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.engine.messages, [{"role": "user", "content": "hello"}])
        self.assertEqual(response.json()["usage"], {
            "prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11})

    async def test_stream_usage(self):
        response = await self.post(stream=True, stream_options={"include_usage": True})
        frames = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
        self.assertEqual(frames[-1], "[DONE]")
        chunks = [json.loads(frame) for frame in frames[:-1]]
        self.assertEqual(chunks[1]["choices"][0]["delta"]["content"], "hello")
        self.assertEqual(chunks[-2]["choices"][0]["finish_reason"], "length")
        self.assertEqual(chunks[-1]["usage"]["completion_tokens"], 3)
        self.assertEqual(chunks[-1]["choices"], [])

    async def test_invalid_requests_do_not_generate(self):
        for options, status in [({"model": "other"}, 404), ({"max_tokens": 0}, 400),
                                ({"max_tokens": 17}, 400),
                                ({"max_tokens": 2, "max_completion_tokens": 2}, 400),
                                ({"stream_options": {"include_usage": True}}, 400)]:
            with self.subTest(options=options):
                self.assertEqual((await self.post(**options)).status_code, status)
        self.engine.prompt = list(range(21))
        self.assertEqual((await self.post()).status_code, 400)
        self.engine.prompt = list(range(20))
        response = await self.post(max_tokens=13)
        self.assertEqual(response.status_code, 400)
        self.assertIn("--n-ctx", response.text)
        self.assertEqual(self.engine.calls, 0)
        self.assertEqual((await self.post(max_tokens=12)).status_code, 200)

    async def test_generation_errors_are_reported(self):
        self.engine.fail = True
        with self.assertLogs(level="ERROR"):
            response = await self.post()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private model error", response.text)
        with self.assertLogs(level="ERROR"):
            response = await self.post(stream=True)
        self.assertIn('"type": "server_error"', response.text)
        self.assertNotIn("[DONE]", response.text)

    async def check_cancellation(self, stream, disconnect):
        self.engine.release.clear()
        incoming = asyncio.Queue()
        incoming.put_nowait({"type": "http.request", "body": json.dumps(
            self.payload(stream=stream)).encode(), "more_body": False})
        sent = []

        async def send(message):
            sent.append(message)

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
                 "http_version": "1.1", "method": "POST", "scheme": "http",
                 "path": "/v1/chat/completions", "query_string": b"",
                 "headers": [(b"content-type", b"application/json")],
                 "client": ("test", 123), "server": ("test", 80)}
        first = asyncio.create_task(self.app(scope, incoming.get, send))
        second = None
        try:
            self.assertTrue(await asyncio.to_thread(self.engine.entered.wait, 2))
            if disconnect:
                incoming.put_nowait({"type": "http.disconnect"})
            else:
                first.cancel()
            await asyncio.wait_for(asyncio.gather(first, return_exceptions=True), 1)
            self.assertTrue(self.engine.cancel.is_set())
            response = await asyncio.wait_for(self.client.get("/healthz"), 1)
            self.assertEqual(response.status_code, 200)
            second = asyncio.create_task(self.post())
            await asyncio.sleep(0.05)
            self.assertFalse(second.done())
            self.assertEqual(self.engine.calls, 1)
            self.engine.release.set()
            self.assertEqual((await asyncio.wait_for(second, 2)).status_code, 200)
            self.assertEqual(self.engine.calls, 2)
        finally:
            self.engine.release.set()
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            if second:
                await asyncio.gather(second, return_exceptions=True)

    async def test_cancelled_completion_stays_serialized(self):
        await self.check_cancellation(stream=False, disconnect=False)

    async def test_disconnected_completion_stays_serialized(self):
        await self.check_cancellation(stream=False, disconnect=True)

    async def test_cancelled_stream_keeps_health_responsive(self):
        await self.check_cancellation(stream=True, disconnect=False)

    async def test_disconnected_stream_keeps_health_responsive(self):
        await self.check_cancellation(stream=True, disconnect=True)

    def test_settings_validation(self):
        for options in [{"n_ctx": 0}, {"n_threads": -1}, {"max_output_tokens": 1}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                Settings(**options)


if __name__ == "__main__":
    unittest.main()
