"""Check real KV handoff, HTTP routing, and equal MPS resource budgets."""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import replace
import gc
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import tracemalloc
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    import httpx
    import torch
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import LlamaConfig, LlamaForCausalLM, PreTrainedTokenizerFast
    from transformer.base.engine import EngineSettings, Generation, TorchEngine
    from transformer.pd.engine import PDEngine
    from transformer.pd import protocol, router, server
except ImportError:
    torch = None


class TinyModel:
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.model_path = Path(cls.directory.name)
        torch.manual_seed(7)
        LlamaForCausalLM(LlamaConfig(
            vocab_size=32, hidden_size=32, intermediate_size=64, num_hidden_layers=2,
            num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=128,
            eos_token_id=2, pad_token_id=0,
        )).save_pretrained(cls.model_path)
        tokenizer = Tokenizer(WordLevel({f"t{i}": i for i in range(32)}, unk_token="t1"))
        tokenizer.pre_tokenizer = Whitespace()
        fast = PreTrainedTokenizerFast(tokenizer_object=tokenizer, eos_token="t2", pad_token="t0")
        fast.chat_template = "{% for m in messages %}{{ m['content'] }} {% endfor %}t3"
        fast.save_pretrained(cls.model_path)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()


@unittest.skipIf(torch is None, "Install Transformers and PD requirements")
class EngineTests(TinyModel, unittest.TestCase):
    def setUp(self):
        settings = EngineSettings(self.model_path, n_ctx=64, n_threads=1)
        self.prefill, self.decode = PDEngine(settings), PDEngine(settings)
        self.base = TorchEngine(settings)
        for engine in (self.prefill, self.decode, self.base):
            self.addCleanup(engine.close)

    def handoff(self, prompt, count):
        state = self.prefill.prefill(prompt)
        payload = self.prefill.export_state(state)
        metadata = {"fingerprint": self.prefill.fingerprint, "prompt": prompt,
                    "max_tokens": count, "metrics": state.metrics}
        metadata, payload = protocol.unpack(protocol.pack(metadata, payload))
        return metadata, payload

    def test_handoff_matches_aggregate_and_generate_without_second_prefill(self):
        for prompt, count in [([4], 1), ([4, 5, 6, 7], 8), ([4] * 40, 8)]:
            with self.subTest(prompt_length=len(prompt), output=count):
                expected = self.base.generate(Generation(prompt, count, 0, 1, True, threading.Event()))
                aggregate = self.prefill.decode(self.prefill.prefill(prompt), count, True, threading.Event())
                metadata, payload = self.handoff(prompt, count)
                with patch.object(self.decode.model, "forward", wraps=self.decode.model.forward) as forward:
                    restored = self.decode.import_state(metadata, payload)
                    actual = self.decode.decode(restored, count, True, threading.Event())
                self.assertEqual({k: actual[k] for k in expected}, expected)
                self.assertEqual({k: aggregate[k] for k in expected}, expected)
                self.assertEqual(len(forward.call_args_list), count - 1)
                for index, call in enumerate(forward.call_args_list):
                    self.assertEqual(tuple(call.kwargs["input_ids"].shape), (1, 1))
                    self.assertEqual(call.kwargs["cache_position"].tolist(), [len(prompt) + index])
                self.assertGreater(actual["metrics"]["kv_bytes"], 0)

    def test_reject_wrong_model_corruption_and_tensor_shape(self):
        from safetensors.torch import load, save

        metadata, payload = self.handoff([4, 5], 3)
        with self.assertRaisesRegex(ValueError, "fingerprints"):
            self.decode.import_state({**metadata, "fingerprint": "different"}, payload)
        with self.assertRaisesRegex(ValueError, "safetensors"):
            self.decode.import_state(metadata, b"corrupt")
        tensors = load(payload)
        tensors["key.0"] = tensors["key.0"][:, :, :1, :].contiguous()
        with self.assertRaisesRegex(ValueError, "shape"):
            self.decode.import_state(metadata, save(tensors))
        with self.assertRaisesRegex(ValueError, "token IDs"):
            self.decode.import_state({**metadata, "prompt": [32]}, payload)

    def test_eos_and_cancellation(self):
        state = self.prefill.prefill([4, 5])
        state.logits = state.logits.clone()
        state.logits.fill_(-100)
        state.logits[:, 2] = 100
        with patch.object(self.prefill.model, "forward") as forward:
            result = self.prefill.decode(state, 3, False, threading.Event())
        forward.assert_not_called()
        self.assertEqual((result["completion_tokens"], result["finish_reason"]), (0, "stop"))
        cancel = threading.Event()
        cancel.set()
        self.assertEqual(self.prefill.decode(state, 3, True, cancel)["completion_tokens"], 0)

    def test_protocol_rejects_bad_headers(self):
        for data in (b"", b"junk", b"\0\0\0\x02{}x", b"\0\0\0\x02[]x"):
            with self.assertRaises(ValueError):
                protocol.unpack(data)


if torch is not None:
    class ClusterTransport(httpx.AsyncBaseTransport):
        def __init__(self, apps):
            self.transports = {name: httpx.ASGITransport(app) for name, app in apps.items()}
            self.calls = []

        async def handle_async_request(self, request):
            self.calls.append((request.url.host, request.url.path))
            return await self.transports[request.url.host].handle_async_request(request)


@unittest.skipIf(torch is None, "Install Transformers and PD requirements")
class APITests(TinyModel, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = AsyncExitStack()
        await self.stack.__aenter__()
        self.addAsyncCleanup(self.stack.aclose)
        self.settings = server.Settings(model=self.model_path, n_ctx=64, n_threads=1,
                                        max_input_tokens=48, max_output_tokens=16, default_output_tokens=4)
        self.apps = {role: server.create_app(replace(self.settings, role=role))
                     for role in ("aggregated", "prefill", "decode")}
        self.apps["aggregate2"] = server.create_app(self.settings)
        for app in self.apps.values():
            await self.stack.enter_async_context(app.router.lifespan_context(app))
        self.transport = ClusterTransport(self.apps)
        self.body = {"model": self.settings.served_model_name,
                     "messages": [{"role": "user", "content": "t4 t5 t6"}],
                     "max_tokens": 6, "ignore_eos": True}

    async def client(self, mode="aggregated", max_pending=8):
        app = router.create_app(router.Settings(mode=mode, aggregate_urls=("http://aggregated", "http://aggregate2"),
                                                prefill_url="http://prefill", decode_url="http://decode",
                                                max_pending=max_pending), transport=self.transport)
        await self.stack.enter_async_context(app.router.lifespan_context(app))
        return await self.stack.enter_async_context(httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://router"))

    async def test_both_paths_stream_and_usage_match(self):
        results = []
        for mode in ("aggregated", "disaggregated"):
            client = await self.client(mode)
            self.assertEqual((await client.get("/readyz")).status_code, 200)
            response = await client.post("/v1/chat/completions", json=self.body)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            results.append(result)
            self.assertEqual(result["metrics"]["mode"], mode)
            stream = await client.post("/v1/chat/completions", json={**self.body, "stream": True,
                                       "stream_options": {"include_usage": True}})
            frames = [line[6:] for line in stream.text.splitlines() if line.startswith("data: ")]
            self.assertEqual(frames[-1], "[DONE]")
            chunks = [json.loads(frame) for frame in frames[:-1]]
            text = "".join(c["delta"].get("content", "") for chunk in chunks for c in chunk.get("choices", []))
            self.assertEqual(text, result["choices"][0]["message"]["content"])
            self.assertEqual(chunks[-1]["usage"], result["usage"])
            self.assertIn("metrics", chunks[-2])
        self.assertEqual(results[0]["choices"], results[1]["choices"])
        self.assertEqual(results[0]["usage"], results[1]["usage"])
        self.assertEqual(results[0]["metrics"]["state_bytes"], 0)
        self.assertGreater(results[1]["metrics"]["state_bytes"], 0)
        self.assertIn(("aggregate2", "/v1/chat/completions"), self.transport.calls)

    async def test_router_releases_uploaded_state_when_http_metadata_is_retained(self):
        size = 1024 * 1024
        uploads = []

        class Backends(httpx.AsyncBaseTransport):
            async def handle_async_request(inner, request):
                if request.url.path == "/internal/prefill":
                    return httpx.Response(200, content=b"x" * size)
                received = 0
                async for chunk in request.stream:
                    self.assertEqual(chunk, b"x" * len(chunk))
                    received += len(chunk)
                self.assertEqual(received, size)
                # HTTP responses and tracing tools may retain request metadata.
                uploads.append(request)
                return httpx.Response(200, content=b"data: [DONE]\n\n")

        app = router.create_app(router.Settings(mode="disaggregated"), transport=Backends())
        await self.stack.enter_async_context(app.router.lifespan_context(app))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://router") as client:
            gc.collect()
            tracemalloc.start()
            try:
                for _ in range(24):
                    response = await client.post("/v1/chat/completions", json={**self.body, "stream": True})
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("[DONE]", response.text)
                gc.collect()
                retained, _ = tracemalloc.get_traced_memory()
                self.assertEqual(len(uploads), 24)
                self.assertLess(retained, 4 * size, "Completed uploads retain KV bodies")
            finally:
                tracemalloc.stop()

    async def test_limits_errors_and_no_wrong_role_fallback(self):
        for mode in ("aggregated", "disaggregated"):
            client = await self.client(mode)
            for options in ({"temperature": 0.5}, {"max_tokens": 17},
                            {"messages": [{"role": "user", "content": "t4 " * 50}]}):
                response = await client.post("/v1/chat/completions", json={**self.body, **options})
                self.assertEqual(response.status_code, 400, response.text)
        client = httpx.AsyncClient(transport=self.transport)
        async with client:
            self.assertEqual((await client.post("http://decode/v1/chat/completions", json=self.body)).status_code, 404)
            response = await client.post("http://decode/internal/decode", content=b"corrupt")
            self.assertEqual(response.status_code, 400)

    async def test_prefill_of_next_request_overlaps_previous_decode(self):
        client = await self.client("disaggregated")
        started, release, second_prefill = threading.Event(), threading.Event(), threading.Event()
        decoder = self.apps["decode"].state.engine
        prefiller = self.apps["prefill"].state.engine
        decode_method = "packed_forward" if hasattr(decoder, "packed_forward") else "decode"
        prefill_method = "packed_forward" if hasattr(prefiller, "packed_forward") else "prefill"
        original_decode, original_prefill = getattr(decoder, decode_method), getattr(prefiller, prefill_method)
        calls = 0

        def blocked_decode(*args, **kwargs):
            started.set()
            if not release.wait(10):
                raise RuntimeError("Test decode timed out")
            return original_decode(*args, **kwargs)

        def observed_prefill(*args):
            nonlocal calls
            value = original_prefill(*args)
            calls += 1
            if calls == 2:
                second_prefill.set()
            return value

        tasks = []
        with patch.object(decoder, decode_method, side_effect=blocked_decode), \
                patch.object(prefiller, prefill_method, side_effect=observed_prefill):
            try:
                tasks.append(asyncio.create_task(client.post("/v1/chat/completions", json=self.body)))
                self.assertTrue(await asyncio.to_thread(started.wait, 5))
                tasks.append(asyncio.create_task(client.post("/v1/chat/completions", json=self.body)))
                self.assertTrue(await asyncio.to_thread(second_prefill.wait, 5))
            finally:
                release.set()
                responses = await asyncio.gather(*tasks)
        self.assertTrue(all(r.status_code == 200 for r in responses))

    async def test_router_admission_returns_429_without_unbounded_queue(self):
        client = await self.client(max_pending=1)
        started, release = threading.Event(), threading.Event()
        engine = self.apps["aggregated"].state.engine
        method = "packed_forward" if hasattr(engine, "packed_forward") else "prefill"
        original = getattr(engine, method)

        def blocked(prompt):
            started.set()
            release.wait(5)
            return original(prompt)

        with patch.object(engine, method, side_effect=blocked):
            first = asyncio.create_task(client.post("/v1/chat/completions", json=self.body))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 5))
                response = await client.post("/v1/chat/completions", json=self.body)
                self.assertEqual(response.status_code, 429)
            finally:
                release.set()
                self.assertEqual((await first).status_code, 200)

    async def test_backend_failure_readiness_and_state_limit(self):
        async def failure(request):
            if request.url.path == "/readyz":
                return httpx.Response(503)
            raise httpx.ConnectError("offline")

        app = router.create_app(transport=httpx.MockTransport(failure))
        await self.stack.enter_async_context(app.router.lifespan_context(app))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            self.assertEqual((await client.get("/readyz")).status_code, 503)
            response = await client.post("/v1/chat/completions", json=self.body)
            self.assertEqual(response.status_code, 502)

        async def oversized():
            yield b"123"
            yield b"456"

        with self.assertRaisesRegex(ValueError, "byte limit"):
            await protocol.read_limited(oversized(), 5)

    async def test_metadata_errors_and_sampling_are_rejected_before_forward(self):
        async with httpx.AsyncClient(transport=self.transport) as client:
            response = await client.post("http://prefill/internal/prefill", json=self.body)
            self.assertEqual(response.status_code, 200)
            metadata, tensors = protocol.unpack(response.content)
            for changed in ({**metadata, "fingerprint": "wrong"},
                            {**metadata, "max_tokens": 1}, {"version": 1}):
                with patch.object(self.apps["decode"].state.engine.model, "forward") as forward:
                    response = await client.post("http://decode/internal/decode",
                                                 content=protocol.pack(changed, tensors))
                self.assertEqual(response.status_code, 400)
                forward.assert_not_called()


@unittest.skipIf(torch is None, "Install Transformers and PD requirements")
class RouterMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = AsyncExitStack()
        await self.stack.__aenter__()
        self.addAsyncCleanup(self.stack.aclose)
        self.body = {"model": router.Settings.served_model_name, "stream": True,
                     "messages": [{"role": "user", "content": "test"}], "max_tokens": 16}

    async def client(self, transport, **options):
        app = router.create_app(router.Settings(mode="disaggregated", **options), transport=transport)
        await self.stack.enter_async_context(app.router.lifespan_context(app))
        return await self.stack.enter_async_context(httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://router"))

    async def test_transfer_slots_bound_prefill_and_recover_after_waiter_cancellation(self):
        release, full = asyncio.Event(), asyncio.Event()
        prefills = 0

        class Backends(httpx.AsyncBaseTransport):
            async def handle_async_request(inner, request):
                nonlocal prefills
                if request.url.path == "/internal/prefill":
                    prefills += 1
                    return httpx.Response(200, content=b"x" * 1024 * 1024)
                if prefills == 2:
                    full.set()
                await release.wait()
                async for _ in request.stream:
                    pass
                return httpx.Response(200, content=b"data: [DONE]\n\n")

        client = await self.client(Backends(), max_state_transfers=2)
        tasks = [asyncio.create_task(client.post("/v1/chat/completions", json=self.body)) for _ in range(8)]
        try:
            await asyncio.wait_for(full.wait(), 2)
            await asyncio.sleep(0.05)
            self.assertEqual(prefills, 2, "Queued requests must wait before allocating KV state")
            self.assertEqual((await client.post("/v1/chat/completions", json=self.body)).status_code, 429)
            tasks[-1].cancel()
            with self.assertRaises(asyncio.CancelledError):
                await tasks[-1]
            release.set()
            responses = await asyncio.wait_for(asyncio.gather(*tasks[:-1]), 5)
            self.assertTrue(all(r.status_code == 200 for r in responses))
            self.assertEqual((await client.post("/v1/chat/completions", json=self.body)).status_code, 200)
            self.assertEqual(prefills, 8)
        finally:
            release.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_failed_and_cancelled_uploads_release_bodies_and_slots(self):
        retained, started = [], asyncio.Event()
        failure = "before"
        size = 1024 * 1024

        class Backends(httpx.AsyncBaseTransport):
            async def handle_async_request(inner, request):
                if request.url.path == "/internal/prefill":
                    return httpx.Response(200, content=b"x" * size)
                retained.append(request)
                if failure != "before":
                    iterator = request.stream.__aiter__()
                    self.assertLessEqual(len(await anext(iterator)), 64 * 1024)
                if failure == "cancel":
                    started.set()
                    await asyncio.Event().wait()
                if failure != "success":
                    raise httpx.WriteError("Upload interrupted", request=request)
                async for _ in iterator:
                    pass
                return httpx.Response(200, content=b"data: [DONE]\n\n")

        client = await self.client(Backends(), max_state_transfers=1)
        gc.collect()
        tracemalloc.start()
        try:
            for failure in ("before", "partial", "cancel"):
                for _ in range(12):
                    started.clear()
                    task = asyncio.create_task(client.post("/v1/chat/completions", json=self.body))
                    try:
                        if failure == "cancel":
                            await asyncio.wait_for(started.wait(), 2)
                            task.cancel()
                            with self.assertRaises(asyncio.CancelledError):
                                await task
                        else:
                            self.assertEqual((await asyncio.wait_for(task, 2)).status_code, 502)
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
            failure = "success"
            self.assertEqual((await client.post("/v1/chat/completions", json=self.body)).status_code, 200)
            gc.collect()
            self.assertEqual(len(retained), 37)
            self.assertLess(tracemalloc.get_traced_memory()[0], 4 * size)
        finally:
            tracemalloc.stop()

    async def test_transfer_wait_times_out_without_starting_another_prefill(self):
        started, release = asyncio.Event(), asyncio.Event()
        prefills = 0

        class Backends(httpx.AsyncBaseTransport):
            async def handle_async_request(inner, request):
                nonlocal prefills
                if request.url.path == "/internal/prefill":
                    prefills += 1
                    return httpx.Response(200, content=b"state")
                started.set()
                await release.wait()
                async for _ in request.stream:
                    pass
                return httpx.Response(200, content=b"data: [DONE]\n\n")

        client = await self.client(Backends(), max_state_transfers=1, timeout_seconds=0.05)
        task = asyncio.create_task(client.post("/v1/chat/completions", json=self.body))
        try:
            await asyncio.wait_for(started.wait(), 2)
            self.assertEqual((await client.post("/v1/chat/completions", json=self.body)).status_code, 504)
            self.assertEqual(prefills, 1)
        finally:
            release.set()
            self.assertEqual((await asyncio.wait_for(task, 2)).status_code, 200)

    async def test_prefill_failure_and_oversized_state_release_slot(self):
        status, size = 503, 10

        class Backends(httpx.AsyncBaseTransport):
            async def handle_async_request(inner, request):
                if request.url.path == "/internal/prefill":
                    return httpx.Response(status, content=b"x" * size)
                async for _ in request.stream:
                    pass
                return httpx.Response(200, content=b"data: [DONE]\n\n")

        client = await self.client(Backends(), max_state_transfers=1, max_state_mib=1)
        self.assertEqual((await client.post("/v1/chat/completions", json=self.body)).status_code, 503)
        status, size = 200, 1024 * 1024 + 1
        self.assertEqual((await client.post("/v1/chat/completions", json=self.body)).status_code, 400)
        size = 16
        self.assertEqual((await client.post("/v1/chat/completions", json=self.body)).status_code, 200)

    async def test_three_decode_backends_stream_concurrently_and_all_affect_readiness(self):
        release, all_started = asyncio.Event(), asyncio.Event()
        decodes, readiness = [], []
        unhealthy = None

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(inner):
                await release.wait()
                yield b"data: [DONE]\n\n"

        class Backends(httpx.AsyncBaseTransport):
            async def handle_async_request(inner, request):
                if request.url.path == "/readyz":
                    readiness.append(request.url.host)
                    return httpx.Response(503 if request.url.host == unhealthy else 200)
                if request.url.path == "/internal/prefill":
                    return httpx.Response(200, content=b"state")
                self.assertEqual(request.url.path, "/internal/decode")
                async for _ in request.stream:
                    pass
                decodes.append(request.url.host)
                if len(decodes) == 3:
                    all_started.set()
                return httpx.Response(200, stream=Stream())

        client = await self.client(Backends(), decode_urls=tuple(f"http://decode{i}" for i in range(3)))
        self.assertEqual((await client.get('/readyz')).status_code, 200)
        self.assertEqual(set(readiness), {'pd-prefill', 'decode0', 'decode1', 'decode2'})
        unhealthy = 'decode2'
        self.assertEqual((await client.get('/readyz')).status_code, 503)
        tasks = [asyncio.create_task(client.post('/v1/chat/completions', json=self.body)) for _ in range(3)]
        try:
            await asyncio.wait_for(all_started.wait(), 2)
            self.assertEqual(decodes, ['decode0', 'decode1', 'decode2'])
        finally:
            release.set()
            responses = await asyncio.wait_for(asyncio.gather(*tasks), 5)
        self.assertTrue(all(r.status_code == 200 and '[DONE]' in r.text for r in responses))
        for _ in range(3):
            self.assertEqual((await client.post('/v1/chat/completions', json=self.body)).status_code, 200)
        self.assertEqual(decodes, ['decode0', 'decode1', 'decode2'] * 2)


class ManifestTests(unittest.TestCase):
    def test_scheduled_overlays_keep_four_shares_and_enable_all_worker_schedulers(self):
        import yaml

        if not shutil.which("kubectl"):
            self.skipTest("kubectl required")
        for mode in ("aggregated", "disaggregated"):
            docs = list(yaml.safe_load_all(subprocess.check_output(
                ["kubectl", "kustomize", str(ROOT / "k8s/gpu-mps-4/pd-scheduled" / mode)], text=True)))
            self.assertTrue(all(d["metadata"]["namespace"] == "pd-comparison-4-scheduled" for d in docs))
            gpu = [d for d in docs if d["kind"] in {"Deployment", "StatefulSet"}
                   and d["metadata"]["name"] != "pd-router"]
            self.assertEqual(sum(d["spec"]["replicas"] for d in gpu), 4)
            for d in gpu:
                container = d["spec"]["template"]["spec"]["containers"][0]
                args = container["args"]
                self.assertEqual(args[args.index("--scheduler") + 1], "token-budget")
                self.assertEqual(container["resources"]["limits"]["nvidia.com/gpu.shared"], 1)
                self.assertEqual(container["image"], "local/transformers-pd-gpu:token-budget-v1")
            config = next(d for d in docs if d["kind"] == "ConfigMap")["data"]
            self.assertEqual((config["MAX_PENDING"], config["MAX_STATE_TRANSFERS"]), ("32", "2"))

    def test_four_slot_overlays_have_equal_budgets_and_direct_pod_routes(self):
        import yaml

        if not shutil.which('kubectl'):
            self.skipTest('kubectl required')
        for mode in ('aggregated', 'disaggregated'):
            docs = list(yaml.safe_load_all(subprocess.check_output(
                ['kubectl', 'kustomize', str(ROOT / 'k8s/gpu-mps-4/pd' / mode)], text=True)))
            self.assertTrue(all(d['metadata']['namespace'] == 'pd-comparison-4' for d in docs))
            workloads = [d for d in docs if d['kind'] in ('Deployment', 'StatefulSet')]
            gpu = [d for d in workloads if d['metadata']['name'] != 'pd-router']
            self.assertEqual(sum(d['spec']['replicas'] for d in gpu), 4)
            for d in gpu:
                c = d['spec']['template']['spec']['containers'][0]
                self.assertEqual(c['resources']['requests'], {'cpu':'1', 'memory':'2Gi', 'nvidia.com/gpu.shared':1})
                self.assertEqual(c['resources']['limits'], {'cpu':'2', 'memory':'2Gi', 'nvidia.com/gpu.shared':1})
            gateway = next(d for d in workloads if d['metadata']['name'] == 'pd-router')
            args = gateway['spec']['template']['spec']['containers'][0]['args']
            role, count = ('aggregate', 4) if mode == 'aggregated' else ('decode', 3)
            self.assertEqual(args[-count:], [f'http://pd-{role}-{i}.pd-{role}:8000' for i in range(count)])
            stateful = next(d for d in gpu if d['metadata']['name'] == f'pd-{role}')
            self.assertEqual((stateful['kind'], stateful['spec']['replicas']), ('StatefulSet', count))
            self.assertEqual(stateful['spec']['serviceName'], f'pd-{role}')
            service = next(d for d in docs if d['kind'] == 'Service' and d['metadata']['name'] == f'pd-{role}')
            self.assertEqual(service['spec']['clusterIP'], 'None')
            config = next(d for d in docs if d['kind'] == 'ConfigMap')
            self.assertEqual(config['data']['MAX_STATE_TRANSFERS'], '2')

    def test_worker_budgets_and_roles(self):
        import yaml

        budgets = []
        for mode in ("aggregated", "disaggregated"):
            docs = list(yaml.safe_load_all((ROOT / "k8s/gpu-mps/pd" / mode / "workers.yaml").read_text()))
            workloads = [d for d in docs if d["kind"] in {"Deployment", "StatefulSet"}]
            roles, slots, cpu, memory = [], 0, 0, 0
            for workload in workloads:
                spec = workload["spec"]["template"]["spec"]
                count = workload["spec"]["replicas"]
                container = spec["containers"][0]
                resources = container["resources"]
                self.assertEqual(spec["runtimeClassName"], "nvidia")
                self.assertEqual(resources["limits"]["nvidia.com/gpu.shared"], 1)
                slots += count * resources["requests"]["nvidia.com/gpu.shared"]
                cpu += count * int(resources["limits"]["cpu"])
                memory += count * int(resources["limits"]["memory"].removesuffix("Gi"))
                roles.extend([container["args"][1]] * count)
            self.assertEqual(slots, 2)
            self.assertEqual(roles, ["aggregated", "aggregated"] if mode == "aggregated" else ["prefill", "decode"])
            budgets.append((slots, cpu, memory))
        self.assertEqual(budgets[0], budgets[1])

    def test_rendered_router_targets_both_baseline_replicas(self):
        import yaml

        if not shutil.which("kubectl"):
            self.skipTest("kubectl required")
        for mode in ("aggregated", "disaggregated"):
            rendered = subprocess.check_output(["kubectl", "kustomize", str(ROOT / "k8s/gpu-mps/pd" / mode)], text=True)
            docs = list(yaml.safe_load_all(rendered))
            gateway = next(d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == "pd-router")
            spec = gateway["spec"]["template"]["spec"]
            container = spec["containers"][0]
            self.assertNotIn("runtimeClassName", spec)
            self.assertNotIn("nvidia.com/gpu.shared", container["resources"]["limits"])
            self.assertEqual(container["env"][0]["value"], mode)
            config = next(d for d in docs if d["kind"] == "ConfigMap")
            self.assertEqual(config["data"]["MAX_STATE_TRANSFERS"], "2")
            self.assertIn("--max-state-transfers", container["args"])
            self.assertEqual(container["resources"]["requests"]["memory"], "512Mi")
            self.assertEqual(container["resources"]["limits"]["memory"], "1Gi")
            self.assertEqual(container["envFrom"][0]["configMapRef"]["name"], config["metadata"]["name"])
            self.assertTrue(all(d["metadata"]["namespace"] == "pd-comparison" for d in docs))


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts/lib").mkdir(parents=True)
        for name in ("deploy-pd.sh", "lib/gpu-settings.sh", "lib/pd-settings.sh"):
            shutil.copyfile(ROOT / "scripts" / name, self.root / "scripts" / name)
        self.trace = self.root / "trace.jsonl"
        self.mock = self.root / "scripts/local-k8s-gpu.sh"
        self.mock.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['PD_TRACE'], 'a') as f:
    f.write(json.dumps(args) + '\\n')
if args[1:3] == ['get', 'nodes']: print(os.environ.get('PD_SLOTS', '2'))
elif 'jobs' in args: print(os.environ.get('PD_ACTIVE', ''))
''')
        self.mock.chmod(0o755)
        self.env = {**os.environ, "GPU_SHARING": "mps", "MPS_REPLICAS": "2", "PD_TRACE": str(self.trace)}
        self.env.pop("CLUSTER_NAME", None)

    def run_deploy(self, **env):
        return subprocess.run(["sh", str(self.root / "scripts/deploy-pd.sh"), "disaggregated"],
                              env={**self.env, **env}, capture_output=True, text=True, timeout=10)

    def test_switch_waits_for_old_pods_and_keeps_results(self):
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.trace.read_text().splitlines()]
        wait = next(i for i, call in enumerate(calls) if "--for=delete" in call)
        apply = next(i for i, call in enumerate(calls) if "-k" in call)
        self.assertLess(wait, apply)
        self.assertFalse(any("namespace" in c or "pvc" in c or "job" in c for c in calls if "delete" in c))

    def test_refuse_active_benchmark_or_missing_slots_before_delete(self):
        for env in ({"PD_ACTIVE": "1"}, {"PD_SLOTS": "1"}, {"GPU_SHARING": "none"},
                    {"MPS_REPLICAS": "4", "PD_SLOTS": "2"}):
            self.trace.write_text("")
            result = self.run_deploy(**env)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('"delete"', self.trace.read_text())

    def test_four_slot_deploy_only_mutates_its_namespace(self):
        result = self.run_deploy(MPS_REPLICAS='4', PD_SLOTS='4')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.trace.read_text().splitlines()]
        self.assertTrue(any('statefulset/pd-decode' in c for c in calls))
        self.assertTrue(any(str(self.root / 'k8s/gpu-mps-4/pd/disaggregated') in c for c in calls))
        for call in calls:
            if '-n' in call:
                self.assertEqual(call[call.index('-n') + 1], 'pd-comparison-4')

    def test_scheduled_deploy_selects_new_namespace_and_budget(self):
        result = self.run_deploy(MPS_REPLICAS="4", PD_SLOTS="4", PD_SCHEDULER="token-budget", PD_TOKEN_BUDGET="32")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.trace.read_text().splitlines()]
        self.assertTrue(any("TOKEN_BUDGET=32" in c for c in calls))
        for call in calls:
            if "-n" in call:
                self.assertEqual(call[call.index("-n") + 1], "pd-comparison-4-scheduled")


if __name__ == "__main__":
    unittest.main()
