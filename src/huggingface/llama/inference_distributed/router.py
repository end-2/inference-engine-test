"""Route both comparison modes through the same CPU-only HTTP gateway."""

import argparse
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import itertools
import math
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
import httpx

from inference import api
from .protocol import CONTENT_TYPE, read_limited
from .runtime import Admission


@dataclass(frozen=True)
class Settings:
    mode: str = "aggregated"
    aggregate_urls: tuple[str, ...] = ("http://pd-aggregate-0.pd-aggregate:8000", "http://pd-aggregate-1.pd-aggregate:8000")
    prefill_url: str = "http://pd-prefill:8000"
    decode_url: str = "http://pd-decode:8000"
    decode_urls: tuple[str, ...] = ()
    served_model_name: str = "HuggingFaceTB/SmolLM2-135M-Instruct"
    max_pending: int = 8
    max_state_mib: int = 64
    max_state_transfers: int = 2
    timeout_seconds: float = 120

    def __post_init__(self):
        if self.mode not in {"aggregated", "disaggregated"}:
            raise ValueError("Unknown routing mode")
        if not self.aggregate_urls or min(self.max_pending, self.max_state_mib, self.max_state_transfers) < 1:
            raise ValueError("Backend URLs and positive limits are required")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        for url in (*self.aggregate_urls, self.prefill_url, self.decode_url, *self.decode_urls):
            parsed = httpx.URL(url)
            if parsed.scheme not in {"http", "https"} or not parsed.host:
                raise ValueError("Invalid backend URL")


class Upload(httpx.AsyncByteStream):
    """Release large bodies even when request metadata or failed uploads survive."""

    def __init__(self, data):
        self.data, self.size = data, len(data)

    async def __aiter__(self):
        try:
            for offset in range(0, self.size, 64 * 1024):
                yield self.data[offset:offset + 64 * 1024]
        finally:
            await self.aclose()

    async def aclose(self):
        self.data = b""


def create_app(settings=None, transport=None):
    settings = settings or Settings()
    decode_urls = settings.decode_urls or (settings.decode_url,)
    backends = (settings.aggregate_urls if settings.mode == "aggregated"
                else (settings.prefill_url, *decode_urls))
    round_robin = itertools.cycle(settings.aggregate_urls)
    decode_round_robin = itertools.cycle(decode_urls)
    limit = settings.max_state_mib * 1024 * 1024
    transfers = asyncio.Semaphore(settings.max_state_transfers)

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=settings.timeout_seconds, transport=transport,
                                     trust_env=False, limits=httpx.Limits(max_connections=32)) as client:
            app.state.client = client
            yield

    app = FastAPI(title=f"PD {settings.mode} router", lifespan=lifespan)
    app.add_middleware(Admission, limit=settings.max_pending)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse(api.error_body(str(exc)), status_code=400)

    @app.exception_handler(httpx.HTTPError)
    async def upstream_error(request, exc):
        status = 504 if isinstance(exc, httpx.TimeoutException) else 502
        return JSONResponse(api.error_body("PD backend unavailable or timed out", "server_error"), status_code=status)

    @app.get("/healthz")
    async def health():
        return {"status": "ok", "mode": settings.mode}

    @app.get("/readyz")
    async def ready():
        responses = await asyncio.gather(*(app.state.client.get(url + "/readyz", timeout=5)
                                          for url in backends), return_exceptions=True)
        healthy = all(isinstance(r, httpx.Response) and r.status_code == 200 for r in responses)
        return JSONResponse({"status": "ready" if healthy else "unavailable", "mode": settings.mode},
                            status_code=200 if healthy else 503)

    @app.get("/v1/models")
    async def models():
        return {"object": "list", "data": [{"id": settings.served_model_name,
                "object": "model", "created": 0, "owned_by": "local"}]}

    async def connected(request, operation):
        task = asyncio.create_task(operation)
        finished = asyncio.Event()

        async def disconnected():
            while not finished.is_set():
                if await request.is_disconnected():
                    return
                if not finished.is_set():
                    await asyncio.sleep(0.1)

        monitor = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait((task, monitor), return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                return await task
            raise asyncio.CancelledError
        finally:
            # is_disconnected uses a cancellation scope, so also signal completion explicitly.
            finished.set()
            for pending in (task, monitor):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(task, monitor, return_exceptions=True)

    async def buffered(upstream):
        try:
            data = await read_limited(upstream.aiter_bytes(), limit)
            return Response(data, status_code=upstream.status_code,
                            media_type=upstream.headers.get("content-type", "application/json"))
        finally:
            await upstream.aclose()

    async def send_payload(url, upload, headers):
        try:
            headers = {**headers, "content-length": str(upload.size)}
            return await app.state.client.send(app.state.client.build_request(
                "POST", url, content=upload, headers=headers), stream=True)
        finally:
            # Transports can fail before consuming the iterator, or during its first chunk.
            await upload.aclose()

    async def handoff(raw):
        queued = time.perf_counter()
        try:
            await asyncio.wait_for(transfers.acquire(), timeout=settings.timeout_seconds)
        except TimeoutError as exc:
            raise httpx.PoolTimeout("Timed out waiting for a state transfer slot") from exc
        upload = None
        try:
            queue_ms = (time.perf_counter() - queued) * 1000
            start = time.perf_counter()
            async with app.state.client.stream("POST", settings.prefill_url + "/internal/prefill",
                                               content=raw, headers={"content-type": "application/json"}) as response:
                if response.status_code != 200:
                    return Response(await read_limited(response.aiter_bytes(), 1024 * 1024),
                                    status_code=response.status_code, media_type="application/json")
                upload = Upload(await read_limited(response.aiter_bytes(), limit))
            return await send_payload(next(decode_round_robin) + "/internal/decode", upload,
                                      {"content-type": CONTENT_TYPE,
                                       "x-pd-state-queue-ms": str(queue_ms),
                                       "x-pd-prefill-rpc-ms": str((time.perf_counter() - start) * 1000)})
        finally:
            if upload is not None:
                await upload.aclose()
            transfers.release()

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        raw = await read_limited(request.stream(), 1024 * 1024)
        body = api.ChatRequest.model_validate_json(raw)
        if body.model != settings.served_model_name:
            return JSONResponse(api.error_body("Unknown model"), status_code=404)
        if settings.mode == "disaggregated":
            upstream = await connected(request, handoff(raw))
            if isinstance(upstream, Response):
                return upstream
        else:
            # Pod-specific URLs prevent HTTP keep-alive from pinning the baseline to one replica.
            url = next(round_robin) + "/v1/chat/completions"
            upstream = await connected(request, send_payload(url, Upload(raw), {"content-type": "application/json"}))
        if upstream.status_code != 200 or not body.stream:
            return await connected(request, buffered(upstream))

        async def stream():
            try:
                async for data in upstream.aiter_bytes():
                    yield data
            except httpx.HTTPError:
                yield api.sse(api.error_body("Backend stream interrupted", "server_error")).encode()
            finally:
                await upstream.aclose()

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("aggregated", "disaggregated"), default="aggregated")
    parser.add_argument("--aggregate-urls", nargs="+", default=Settings.aggregate_urls)
    parser.add_argument("--prefill-url", default=Settings.prefill_url)
    parser.add_argument("--decode-url", default=Settings.decode_url)
    parser.add_argument("--decode-urls", nargs="+", default=Settings.decode_urls,
                        help="Pod-specific decode URLs; overrides --decode-url")
    parser.add_argument("--served-model-name", default=Settings.served_model_name)
    parser.add_argument("--max-pending", type=api.positive_int, default=8)
    parser.add_argument("--max-state-mib", type=api.positive_int, default=64)
    parser.add_argument("--max-state-transfers", type=api.positive_int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=api.positive_int, default=8000)
    options = vars(parser.parse_args())
    host, port = options.pop("host"), options.pop("port")
    try:
        settings = Settings(**options)
    except ValueError as exc:
        parser.error(str(exc))
    import uvicorn

    uvicorn.run(create_app(settings), host=host, port=port, workers=1)


if __name__ == "__main__":
    main()
