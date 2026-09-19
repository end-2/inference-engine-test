"""Exercise both image entrypoints against the existing chat/SSE contract."""

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import unittest

import httpx

from enhanced_support import load_variant
from test_llama_server import FakeEngine

servers = [load_variant(variant, "server") for variant in ["enhanced-batch", "enhanced-cache"]]


class EnhancedAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_extension_settings_reach_engine(self):
        for server, options in zip(servers, [
            dict(n_threads_batch=3, n_ubatch=16, max_parallel=2, prefill_chunk=4),
            dict(cache_dir=Path("/tmp/test-kv"), cache_ram_mib=0,
                 cache_disk_mib=8, cache_min_prefix=2),
        ]):
            settings = server.Settings(model=Path("unused.gguf"), n_ctx=256,
                                       n_batch=32, n_threads=2, **options)
            app = server.create_app(settings, FakeEngine)
            async with app.router.lifespan_context(app):
                received = app.state.engine.settings
                for name, value in dict(model_path=settings.model, n_ctx=256,
                                        n_batch=32, n_threads=2, **options).items():
                    self.assertEqual(getattr(received, name), value)

    def test_extension_settings_validate_with_common_settings(self):
        for server, options in [
            (servers[0], {"max_parallel": 0}),
            (servers[0], {"n_threads_batch": 0}),
            (servers[0], {"n_batch": 2, "max_parallel": 3}),
            (servers[1], {"cache_ram_mib": -1}),
            (servers[1], {"cache_min_prefix": 0}),
        ]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                server.Settings(**options)
        for server in servers:
            with self.assertRaises(ValueError):
                server.Settings(n_ctx=0)

    async def test_failed_worker_is_not_ready_or_healthy(self):
        async with self.fixture(servers[0]) as (app, client, payload):
            app.state.engine.healthy = False
            for path in ("/healthz", "/readyz"):
                response = await client.get(path)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"status": "failed"})

    @asynccontextmanager
    async def fixture(self, server):
        settings = server.Settings(n_ctx=32, max_input_tokens=20,
                                   max_output_tokens=16, default_output_tokens=8)
        app = server.create_app(settings, FakeEngine)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                try:
                    yield app, client, {"model": settings.served_model_name,
                                        "messages": [{"role": "user", "content": "hello"}]}
                finally:
                    app.state.engine.release.set()

    async def test_chat_stream_and_server_token_usage(self):
        for server in servers:
            with self.subTest(server=server.__name__):
                async with self.fixture(server) as (app, client, payload):
                    for stream in [False, True]:
                        body = {**payload, "stream": stream, "ignore_eos": True, "max_completion_tokens": 8}
                        if stream:
                            body["stream_options"] = {"include_usage": True}
                        response = await client.post("/v1/chat/completions", json=body)
                        self.assertEqual(response.status_code, 200)
                        if stream:
                            frames = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
                            self.assertEqual(frames[-1], "[DONE]")
                            result = json.loads(frames[-2])
                        else:
                            result = response.json()
                        self.assertEqual(result["usage"], {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11})
                    for path in ["/healthz", "/readyz", "/v1/models"]:
                        self.assertEqual((await client.get(path)).status_code, 200)

    async def test_validation_and_generation_failure(self):
        for server in servers:
            async with self.fixture(server) as (app, client, payload):
                for options, status in [({"model": "unknown"}, 404), ({"max_tokens": 17}, 400),
                                        ({"max_tokens": 0}, 400), ({"n": 2}, 400),
                                        ({"max_tokens": 2, "max_completion_tokens": 2}, 400),
                                        ({"stream_options": {"include_usage": True}}, 400)]:
                    response = await client.post("/v1/chat/completions", json={**payload, **options})
                    self.assertEqual(response.status_code, status)
                app.state.engine.prompt = list(range(21))
                self.assertEqual((await client.post("/v1/chat/completions", json=payload)).status_code, 400)
                app.state.engine.prompt = list(range(20))
                self.assertEqual((await client.post("/v1/chat/completions", json={**payload, "max_tokens": 13})).status_code, 400)
                app.state.engine.prompt = [1, 2]
                app.state.engine.fail = True
                with self.assertLogs(level="ERROR"):
                    response = await client.post("/v1/chat/completions", json={**payload, "stream": True})
                self.assertIn("server_error", response.text)
                self.assertNotIn("[DONE]", response.text)
                self.assertNotIn("private model error", response.text)

    async def test_disconnect_and_task_cancellation_reach_engine(self):
        for server in servers:
            for stream in [False, True]:
                for disconnect in [False, True]:
                    async with self.fixture(server) as (app, client, payload):
                        engine = app.state.engine
                        engine.release.clear()
                        incoming = asyncio.Queue()
                        incoming.put_nowait({"type": "http.request", "body": json.dumps(
                            {**payload, "stream": stream}).encode(), "more_body": False})
                        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
                                 "http_version": "1.1", "method": "POST", "scheme": "http",
                                 "path": "/v1/chat/completions", "query_string": b"",
                                 "headers": [(b"content-type", b"application/json")],
                                 "client": ("test", 123), "server": ("test", 80)}

                        async def send(message):
                            pass

                        task = asyncio.create_task(app(scope, incoming.get, send))
                        try:
                            self.assertTrue(await asyncio.to_thread(engine.entered.wait, 2))
                            if disconnect:
                                incoming.put_nowait({"type": "http.disconnect"})
                            else:
                                task.cancel()
                            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
                            self.assertTrue(engine.cancel.is_set())
                            self.assertEqual((await client.get("/healthz")).status_code, 200)
                        finally:
                            engine.release.set()
                            task.cancel()
                            await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
