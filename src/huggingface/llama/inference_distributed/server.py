"""Aggregated, prefill-only, and decode-only workers for the PD comparison."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import logging
import threading
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from inference import api
from huggingface.llama import serving as base
from .engine import PDEngine
from .protocol import CONTENT_TYPE, pack, read_limited, unpack
from .runtime import Admission
from .scheduler import TokenScheduler, Work


@dataclass(frozen=True)
class Settings(base.Settings):
    role: str = "aggregated"
    max_pending: int = 8
    max_state_mib: int = 64
    scheduler: str = "serial"
    max_num_batched_tokens: int = 256
    max_num_seqs: int = 8
    max_kv_tokens: int = 8192
    long_prefill_token_threshold: int = 0
    scheduler_trace: bool = False

    def __post_init__(self):
        super().__post_init__()
        if self.role not in {"aggregated", "prefill", "decode"}:
            raise ValueError("Unknown worker role")
        if min(self.max_pending, self.max_state_mib) < 1:
            raise ValueError("Queue and state limits must be positive")
        if self.scheduler not in {"serial", "token-budget"}:
            raise ValueError("Unknown scheduler")
        if min(self.max_num_batched_tokens, self.max_num_seqs, self.max_kv_tokens) < 1:
            raise ValueError("Scheduler limits must be positive")
        if self.long_prefill_token_threshold < 0:
            raise ValueError("Prefill chunk threshold cannot be negative")


def create_app(settings=None, engine_factory=None):
    settings = settings or Settings()
    limit = settings.max_state_mib * 1024 * 1024
    if engine_factory is None:
        if settings.scheduler == "token-budget":
            from .packed import PackedEngine
            engine_factory = PackedEngine
        else:
            engine_factory = PDEngine

    @asynccontextmanager
    async def lifespan(app):
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pd-gpu")
        app.state.executor = executor
        try:
            app.state.engine = await asyncio.get_running_loop().run_in_executor(
                executor, engine_factory, settings.engine_settings())
            if settings.scheduler == "token-budget":
                app.state.scheduler = TokenScheduler(
                    app.state.engine, settings.max_num_batched_tokens, settings.max_num_seqs,
                    settings.max_kv_tokens, settings.long_prefill_token_threshold, settings.scheduler_trace)
            yield
        finally:
            if hasattr(app.state, "scheduler"):
                await asyncio.to_thread(app.state.scheduler.close)
            await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)
            if hasattr(app.state, "engine"):
                app.state.engine.close()

    app = FastAPI(title=f"PD {settings.role} worker", lifespan=lifespan)
    app.add_middleware(Admission, limit=settings.max_pending)

    @app.exception_handler(ValueError)
    async def bad_request(request, exc):
        return JSONResponse(api.error_body(str(exc)), status_code=400)

    @app.get("/healthz")
    @app.get("/readyz")
    async def ready():
        if hasattr(app.state, "scheduler") and app.state.scheduler.closed:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ready", "role": settings.role, "scheduler": settings.scheduler}

    def options(raw):
        body = api.ChatRequest.model_validate(raw)
        if body.model != settings.served_model_name:
            raise ValueError("Unknown model")
        if body.temperature != 0:
            raise ValueError("PD comparison supports greedy decoding (temperature=0)")
        count = body.max_completion_tokens or body.max_tokens or settings.default_output_tokens
        if count > settings.max_output_tokens:
            raise ValueError("Output exceeds --max-output-tokens")
        return body, count

    async def chat_input(request):
        raw = await read_limited(request.stream(), 1024 * 1024)
        body, count = options(json.loads(raw))
        engine = app.state.engine
        prompt = await asyncio.to_thread(engine.prepare_prompt, api.normalize(body))
        check_prompt(prompt, count)
        return body, count, prompt

    def check_prompt(prompt, count):
        app.state.engine.validate_prompt(prompt, count)
        if len(prompt) > settings.max_input_tokens:
            raise ValueError("Input exceeds --max-input-tokens; prompts are not truncated")

    async def events(work, request, streaming):
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        cancel = threading.Event()
        queued = time.perf_counter()

        def publish(kind, value):
            if not cancel.is_set():
                loop.call_soon_threadsafe(queue.put_nowait, (kind, value))

        def run():
            if cancel.is_set():
                return
            try:
                value = work(cancel, lambda text: publish("text", text),
                             (time.perf_counter() - queued) * 1000)
                publish("result", value)
            except ValueError as exc:
                publish("invalid", str(exc))
            except Exception:
                logging.exception("PD inference failed")
                publish("error", "PD inference failed. See worker logs.")

        if isinstance(work, Work):
            def completed(future):
                if future.cancelled():
                    return
                try:
                    publish("result", future.result())
                except ValueError as exc:
                    publish("invalid", str(exc))
                except Exception:
                    logging.exception("PD scheduled inference failed")
                    publish("error", "PD inference failed. See worker logs.")

            # Validation happens before submission so invalid streaming requests
            # also terminate with an error instead of leaving a consumer waiting.
            try:
                future = app.state.scheduler.submit(work, cancel,
                    (lambda text: publish("text", text)) if streaming else None)
            except ValueError as exc:
                yield "invalid", str(exc)
                return
            except RuntimeError:
                yield "error", "Token scheduler is unavailable. See worker logs."
                return
            future.add_done_callback(completed)
        else:
            future = loop.run_in_executor(app.state.executor, run)
        try:
            while True:
                try:
                    kind, value = await asyncio.wait_for(queue.get(), timeout=0.1)
                except TimeoutError:
                    if not streaming and await request.is_disconnected():
                        return
                    continue
                yield kind, value
                if kind != "text":
                    return
        finally:
            cancel.set()
            if not isinstance(work, Work):
                future.cancel()

    async def respond(body, request, work):
        metadata = {"id": f"chatcmpl-{uuid4().hex}", "created": int(time.time()), "model": body.model}

        def log(result):
            logging.getLogger("uvicorn.error").info("pd_request %s", json.dumps({
                "id": metadata["id"], "role": settings.role,
                "prompt_tokens": result["prompt_tokens"], "completion_tokens": result["completion_tokens"],
                **result["metrics"],
            }))

        if body.stream:
            async def stream():
                def chunk(delta, finish=None, **extra):
                    return {**metadata, "object": "chat.completion.chunk",
                            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}], **extra}

                yield api.sse(chunk({"role": "assistant", "content": ""}))
                source = events(work, request, True)
                try:
                    async for kind, value in source:
                        if kind == "text":
                            yield api.sse(chunk({"content": value}))
                        elif kind in {"error", "invalid"}:
                            yield api.sse(api.error_body(value, "server_error"))
                            return
                        else:
                            log(value)
                            yield api.sse(chunk({}, value["finish_reason"], metrics=value["metrics"]))
                            if body.stream_options and body.stream_options.include_usage:
                                yield api.sse({**metadata, "object": "chat.completion.chunk", "choices": [],
                                               "usage": api.usage(value["prompt_tokens"], value["completion_tokens"])})
                    yield "data: [DONE]\n\n"
                finally:
                    await source.aclose()

            return StreamingResponse(stream(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        async for kind, value in events(work, request, False):
            if kind in {"error", "invalid"}:
                return JSONResponse(api.error_body(value), status_code=400 if kind == "invalid" else 500)
            if kind == "result":
                log(value)
                return {**metadata, "object": "chat.completion",
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": value["text"]},
                                     "finish_reason": value["finish_reason"]}],
                        "usage": api.usage(value["prompt_tokens"], value["completion_tokens"]),
                        "metrics": value["metrics"]}
        return Response(status_code=499)

    @app.post("/v1/chat/completions")
    async def aggregated(request: Request):
        if settings.role != "aggregated":
            return Response(status_code=404)
        body, count, prompt = await chat_input(request)

        def work(cancel, emit, queue_ms):
            engine = app.state.engine
            state = engine.prefill(prompt)
            state.metrics.update(mode="aggregated", prefill_queue_ms=queue_ms, decode_queue_ms=0,
                                 export_ms=0, import_ms=0, state_bytes=0, kv_bytes=0)
            return engine.decode(state, count, body.ignore_eos, cancel, emit if body.stream else None)

        if settings.scheduler == "token-budget":
            work = Work("aggregated", prompt, count, body.ignore_eos, metrics={
                "mode": "aggregated", "decode_queue_ms": 0, "export_ms": 0,
                "import_ms": 0, "state_bytes": 0, "kv_bytes": 0})
        return await respond(body, request, work)

    @app.post("/internal/prefill")
    async def prefill(request: Request):
        if settings.role != "prefill":
            return Response(status_code=404)
        body, count, prompt = await chat_input(request)

        def export(engine, state):
            tensors = engine.export_state(state)
            payload = pack({"fingerprint": engine.fingerprint, "prompt": prompt, "max_tokens": count,
                            "request": body.model_dump(), "metrics": state.metrics}, tensors)
            if len(payload) > limit:
                raise ValueError("State exceeds --max-state-mib")
            return payload

        def work(cancel, emit, queue_ms):
            engine = app.state.engine
            state = engine.prefill(prompt)
            state.metrics.update(mode="disaggregated", prefill_queue_ms=queue_ms)
            return export(engine, state)

        if settings.scheduler == "token-budget":
            work = Work("prefill", prompt, count, body.ignore_eos, finish=export,
                        metrics={"mode": "disaggregated"})
        async for kind, value in events(work, request, False):
            if kind == "result":
                return Response(value, media_type=CONTENT_TYPE)
            return JSONResponse(api.error_body(value), status_code=400 if kind == "invalid" else 500)
        return Response(status_code=499)

    @app.post("/internal/decode")
    async def decode(request: Request):
        if settings.role != "decode":
            return Response(status_code=404)
        start = time.perf_counter()
        payload = await read_limited(request.stream(), limit)
        receive_ms = (time.perf_counter() - start) * 1000
        metadata, tensors = unpack(payload)
        if not {"request", "prompt", "max_tokens", "metrics", "fingerprint"} <= metadata.keys():
            raise ValueError("Missing state metadata")
        body, count = options(metadata["request"])
        if count != metadata["max_tokens"] or not isinstance(metadata["metrics"], dict):
            raise ValueError("Invalid state metadata")
        check_prompt(metadata["prompt"], count)
        if metadata["fingerprint"] != app.state.engine.fingerprint:
            raise ValueError("Prefill and decode model fingerprints differ")
        rpc_ms = float(request.headers.get("x-pd-prefill-rpc-ms", "0"))
        state_queue_ms = float(request.headers.get("x-pd-state-queue-ms", "0"))

        def work(cancel, emit, queue_ms):
            engine = app.state.engine
            state = engine.import_state(metadata, tensors)
            state.metrics.update(decode_queue_ms=queue_ms, state_bytes=len(payload),
                                 state_receive_ms=receive_ms, prefill_rpc_ms=rpc_ms,
                                 state_queue_ms=state_queue_ms)
            return engine.decode(state, count, body.ignore_eos, cancel, emit if body.stream else None)

        if settings.scheduler == "token-budget":
            work = Work("decode", metadata["prompt"], count, body.ignore_eos,
                        load=lambda engine: engine.import_state(metadata, tensors), metrics={
                            "state_bytes": len(payload), "state_receive_ms": receive_ms,
                            "prefill_rpc_ms": rpc_ms, "state_queue_ms": state_queue_ms})
        return await respond(body, request, work)

    return app


def main():
    parser = base.create_parser(__doc__)
    parser.add_argument("--role", choices=("aggregated", "prefill", "decode"), default="aggregated")
    parser.add_argument("--max-pending", type=api.positive_int, default=8)
    parser.add_argument("--max-state-mib", type=api.positive_int, default=64)
    parser.add_argument("--scheduler", choices=("serial", "token-budget"), default="serial")
    parser.add_argument("--max-num-batched-tokens", type=api.positive_int, default=256)
    parser.add_argument("--max-num-seqs", type=api.positive_int, default=8)
    parser.add_argument("--max-kv-tokens", type=api.positive_int, default=8192)
    parser.add_argument("--long-prefill-token-threshold", type=int, default=0)
    parser.add_argument("--scheduler-trace", action="store_true")
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
