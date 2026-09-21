"""Metrics preserve base API behavior, including streaming errors and cancellation."""

import asyncio
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import test_server_llamacpp as base_tests

spec = importlib.util.spec_from_file_location(
    "transformers_metric_server", Path(__file__).resolve().parents[1] / "src/transformers_cpu/base_metric/server.py",
)
metric_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metric_server)


class MetricServerTests(base_tests.ServerTests):
    async def asyncSetUp(self):
        with patch("test_server_llamacpp.create_app", metric_server.create_app), patch(
            "test_server_llamacpp.Settings", metric_server.Settings,
        ):
            await super().asyncSetUp()
        self.registry = self.app.state.metrics.registry
        self.engine = self.engine.engine

    def value(self, name, **labels):
        return self.registry.get_sample_value(name, labels)

    async def test_metrics_exclude_probes_and_count_completed_tokens(self):
        await self.client.get("/healthz")
        await self.client.get("/readyz")
        await self.client.get("/v1/models")
        await self.post()
        # Stream token accounting also works without include_usage in the response.
        await self.post(stream=True)
        response = await self.client.get("/metrics")
        self.assertIn("text/plain", response.headers["content-type"])
        self.assertEqual(self.value("transformers_requests_total", status_code="200", outcome="success"), 2)
        self.assertEqual(self.value("transformers_tokens_total", kind="prompt"), 16)
        self.assertEqual(self.value("transformers_tokens_total", kind="completion"), 6)
        self.assertEqual(self.value("transformers_request_duration_seconds_count", outcome="success"), 2)
        self.assertEqual(self.value("transformers_time_to_first_token_seconds_count"), 1)
        self.assertEqual(self.value("transformers_requests_in_flight"), 0)

    async def test_http_and_sse_errors_have_distinct_outcomes(self):
        await self.post(model="missing")
        self.engine.fail = True
        with self.assertLogs(level="ERROR"):
            await self.post()
            await self.post(stream=True)
        for status in ("404", "500", "200"):
            self.assertEqual(self.value("transformers_requests_total", status_code=status, outcome="error"), 1)
        self.assertIsNone(self.value("transformers_requests_total", status_code="200", outcome="success"))
        self.assertEqual(self.value("transformers_tokens_total", kind="completion"), 0)
        self.assertEqual(self.value("transformers_time_to_first_token_seconds_count"), 0)

    async def test_metrics_remain_responsive_while_generation_is_blocked(self):
        self.engine.release.clear()
        task = asyncio.create_task(self.post(stream=True))
        try:
            self.assertTrue(await asyncio.to_thread(self.engine.entered.wait, 2))
            response = await asyncio.wait_for(self.client.get("/metrics"), 1)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.value("transformers_requests_in_flight"), 1)
            self.assertEqual(self.value("transformers_time_to_first_token_seconds_count"), 0)
        finally:
            self.engine.release.set()
            await task
        self.assertEqual(self.value("transformers_requests_in_flight"), 0)

    async def test_disconnected_stream_is_counted(self):
        await self.check_cancellation(stream=True, disconnect=True)
        self.assertEqual(self.value("transformers_requests_total", status_code="200", outcome="disconnected"), 1)
        self.assertEqual(self.value("transformers_requests_in_flight"), 0)

    async def test_app_registries_are_isolated(self):
        await self.post()
        another = metric_server.create_app(self.settings, base_tests.FakeEngine)
        registry = another.state.metrics.registry
        self.assertEqual(registry.get_sample_value("transformers_tokens_total", {"kind": "prompt"}), 0)
        self.assertIsNone(registry.get_sample_value(
            "transformers_requests_total", {"status_code": "200", "outcome": "success"},
        ))


if __name__ == "__main__":
    unittest.main()
