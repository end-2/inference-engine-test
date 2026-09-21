"""Serve the base chat API with request and generation metrics at /metrics."""

import asyncio
import json
import time

from fastapi.responses import Response
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST



class Metrics:
    def __init__(self, prefix):
        self.registry = CollectorRegistry()
        self.requests = Counter(
            f"{prefix}_requests_total", "Finished chat requests, including SSE errors.",
            ["status_code", "outcome"], registry=self.registry,
        )
        self.inflight = Gauge(
            f"{prefix}_requests_in_flight", "Chat requests including queued and streaming work.",
            registry=self.registry,
        )
        buckets = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120)
        self.duration = Histogram(
            f"{prefix}_request_duration_seconds", "Chat latency through the last response body.",
            ["outcome"], buckets=buckets, registry=self.registry,
        )
        self.ttft = Histogram(
            f"{prefix}_time_to_first_token_seconds",
            "Time from chat request arrival to first nonempty streamed content, including queueing.",
            buckets=buckets, registry=self.registry,
        )
        self.tokens = Counter(
            f"{prefix}_tokens_total", "Tokens from completed engine generations.",
            ["kind"], registry=self.registry,
        )
        for kind in ("prompt", "completion"):
            self.tokens.labels(kind)

    def record_tokens(self, result):
        for kind in ("prompt", "completion"):
            self.tokens.labels(kind).inc(result[f"{kind}_tokens"])
        return result


class MeteredEngine:
    def __init__(self, engine, metrics):
        self.engine = engine
        self.metrics = metrics

    def __getattr__(self, name):
        return getattr(self.engine, name)

    def complete(self, *args):
        return self.metrics.record_tokens(self.engine.complete(*args))

    def stream(self, *args):
        return self.metrics.record_tokens(self.engine.stream(*args))


class RequestMetrics:
    """Observe the full ASGI response so an HTTP 200 SSE error is not a success."""

    def __init__(self, app, metrics):
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope["path"] != "/v1/chat/completions"
                or scope["method"] != "POST"):
            return await self.app(scope, receive, send)

        started = time.perf_counter()
        status = 500
        streaming = finished = failed = disconnected = first_token = stream_done = False
        buffer = b""
        self.metrics.inflight.inc()

        async def observed_receive():
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect" and not finished:
                disconnected = True
            return message

        async def observed_send(message):
            nonlocal status, streaming, finished, failed, first_token, stream_done, buffer
            await send(message)
            if message["type"] == "http.response.start":
                status = message["status"]
                streaming = b"text/event-stream" in dict(message["headers"]).get(b"content-type", b"")
            elif message["type"] == "http.response.body":
                if streaming:
                    buffer += message.get("body", b"")
                    while b"\n\n" in buffer:
                        frame, buffer = buffer.split(b"\n\n", 1)
                        if not frame.startswith(b"data: "):
                            continue
                        if frame == b"data: [DONE]":
                            stream_done = True
                            continue
                        payload = json.loads(frame[6:])
                        failed = failed or "error" in payload
                        if not first_token and any(
                            choice.get("delta", {}).get("content")
                            for choice in payload.get("choices", [])
                        ):
                            first_token = True
                            self.metrics.ttft.observe(time.perf_counter() - started)
                finished = not message.get("more_body", False)

        try:
            await self.app(scope, observed_receive, observed_send)
        except (asyncio.CancelledError, OSError):
            disconnected = True
            raise
        except Exception:
            failed = True
            raise
        finally:
            if disconnected or status == 499:
                outcome = "disconnected"
            elif failed or status >= 400 or not finished or (streaming and not stream_done):
                outcome = "error"
            else:
                outcome = "success"
            self.metrics.inflight.dec()
            self.metrics.requests.labels(str(status), outcome).inc()
            self.metrics.duration.labels(outcome).observe(time.perf_counter() - started)


def create_instrumented_app(create_base_app, settings, engine_factory, prefix):
    metrics = Metrics(prefix)
    app = create_base_app(
        settings, lambda options: MeteredEngine(engine_factory(options), metrics),
    )
    app.state.metrics = metrics
    app.add_middleware(RequestMetrics, metrics=metrics)

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics():
        return Response(generate_latest(metrics.registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    return app

