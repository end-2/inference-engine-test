"""Check the shared HTTP contract and settings for each CPU entrypoint."""

import json
from pathlib import Path
import unittest

import httpx

from enhanced_support import ROOT
from test_server_llamacpp import FakeEngine
from transformers_cpu.base import server as base
from transformers_cpu.enhanced.batch import server as batch
from transformers_cpu.enhanced.cache import server as cache


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_contract_for_all_variants(self):
        for server in (base, batch, cache):
            with self.subTest(server=server.__name__):
                settings = server.Settings()
                app = server.create_app(settings, FakeEngine)
                async with app.router.lifespan_context(app):
                    self.assertEqual(app.state.engine.settings, settings.engine_settings())
                    self.assertEqual(app.title, "Transformers CPU inference API")
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                        models = (await client.get("/v1/models")).json()
                        self.assertEqual(models["data"][0]["id"], "HuggingFaceTB/SmolLM2-135M-Instruct")
                        body = {"model": "HuggingFaceTB/SmolLM2-135M-Instruct",
                                "messages": [{"role": "user", "content": "hello"}]}
                        response = await client.post("/v1/chat/completions", json=body)
                        self.assertEqual(response.status_code, 200)
                        expected = response.json()
                        response = await client.post("/v1/chat/completions", json={
                            **body, "stream": True, "stream_options": {"include_usage": True}})
                        frames = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
                        self.assertEqual(frames[-1], "[DONE]")
                        self.assertEqual(json.loads(frames[-2])["usage"], expected["usage"])
                        text = "".join(c["delta"].get("content", "") for f in frames[:-1]
                                       for c in json.loads(f).get("choices", []))
                        self.assertEqual(text, expected["choices"][0]["message"]["content"])
                        for invalid, status in [({"model": "unknown"}, 404), ({"max_tokens": 0}, 400),
                                                ({"max_tokens": 129}, 400), ({"n": 2}, 400)]:
                            response = await client.post("/v1/chat/completions", json={**body, **invalid})
                            self.assertEqual(response.status_code, status)
                        app.state.engine.healthy = False
                        for path in ("/readyz", "/healthz"):
                            self.assertEqual((await client.get(path)).status_code, 503)
                self.assertTrue(app.state.executor._shutdown)

    def test_settings_reject_invalid_cpu_and_extension_options(self):
        for server, values in [(base, {"n_threads": 0}), (base, {"dtype": "float16"}),
                               (batch, {"max_parallel": 0}), (batch, {"batch_wait_ms": -1}),
                               (batch, {"batch_wait_ms": float("nan")}),
                               (cache, {"cache_ram_mib": -1}), (cache, {"cache_min_prefix": 0})]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                server.Settings(**values)

    def test_cache_settings_preserved(self):
        settings = cache.Settings(model=Path("weights"), cache_dir=Path("cache"),
                                  cache_ram_mib=0, cache_disk_mib=2, cache_min_prefix=4)
        engine = settings.engine_settings()
        self.assertEqual((engine.model_path, engine.cache_dir, engine.cache_ram_mib,
                          engine.cache_disk_mib, engine.cache_min_prefix),
                         (Path("weights"), Path("cache"), 0, 2, 4))


if __name__ == "__main__":
    unittest.main()
