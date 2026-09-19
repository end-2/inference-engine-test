"""Serve a local GGUF model on CPU through the chat API used by AIPerf."""

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from functools import partial
import json
import logging
from pathlib import Path
import threading
import time
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine import EngineSettings, LlamaEngine


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextPart(APIModel):
    type: Literal["text"]
    text: str


class Message(APIModel):
    role: Literal["system", "user", "assistant"]
    content: str | list[TextPart]


class StreamOptions(APIModel):
    include_usage: bool = False


class ChatRequest(APIModel):
    model: str
    messages: list[Message] = Field(min_length=1)
    stream: bool = False
    stream_options: StreamOptions | None = None
    max_tokens: int | None = Field(default=None, gt=0, strict=True)
    max_completion_tokens: int | None = Field(default=None, gt=0, strict=True)
    temperature: float = Field(default=0, ge=0, le=2)
    top_p: float = Field(default=1, gt=0, le=1)
    n: Literal[1] = 1
    ignore_eos: bool = False

    @model_validator(mode="after")
    def check_options(self):
        if self.max_tokens is not None and self.max_completion_tokens is not None:
            raise ValueError("Specify only one output token limit.")
        if self.stream_options is not None and not self.stream:
            raise ValueError("stream_options requires stream=true.")
        return self


@dataclass(frozen=True)
class Settings:
    model: Path = Path("/model/model.gguf")
    served_model_name: str = "Qwen/Qwen2.5-0.5B-Instruct"
    n_ctx: int = 2048
    n_batch: int = 512
    n_threads: int = 4
    max_input_tokens: int = 2048
    max_output_tokens: int = 1024
    default_output_tokens: int = 128

    def __post_init__(self):
        for name in ("n_ctx", "n_batch", "n_threads", "max_input_tokens",
                     "max_output_tokens", "default_output_tokens"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be greater than zero")
        if self.default_output_tokens > self.max_output_tokens:
            raise ValueError("default_output_tokens must not exceed max_output_tokens")


def error_body(message, error_type="invalid_request_error"):
    return {"error": {"message": message, "type": error_type, "param": None, "code": None}}


def usage(prompt_tokens, completion_tokens):
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def sse(payload):
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def normalize(body: ChatRequest) -> list[dict]:
    return [
        {
            "role": message.role,
            "content": message.content
            if isinstance(message.content, str)
            else "".join(part.text for part in message.content),
        }
        for message in body.messages
    ]


def create_app(settings=None, engine_factory=LlamaEngine):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine_settings = EngineSettings(
            model_path=settings.model,
            n_ctx=settings.n_ctx,
            n_batch=settings.n_batch,
            n_threads=settings.n_threads,
        )
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="llama")
        app.state.executor = executor
        try:
            app.state.engine = await run_engine(engine_factory, engine_settings)
            try:
                yield
            finally:
                await run_engine(app.state.engine.close)
                del app.state.engine
        finally:
            await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)

    app = FastAPI(title="llama.cpp CPU inference API", lifespan=lifespan)

    def run_engine(function, *args):
        # Cancelling an asyncio future does not stop its native worker. One
        # executor keeps model access serialized until that worker exits.
        return asyncio.get_running_loop().run_in_executor(
            app.state.executor, partial(function, *args)
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse(error_body(str(exc)), status_code=400)

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready():
        return {"status": "ready"}

    @app.get("/v1/models")
    async def models():
        return {
            "object": "list",
            "data": [
                {
                    "id": settings.served_model_name,
                    "object": "model",
                    "created": 0,
                    "owned_by": "local",
                }
            ],
        }

    async def events(prompt, body, output_tokens):
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        cancel = threading.Event()

        def publish(kind, value):
            if not cancel.is_set():
                loop.call_soon_threadsafe(queue.put_nowait, (kind, value))

        def run():
            try:
                result = app.state.engine.stream(
                    prompt, output_tokens, body.temperature, body.top_p,
                    body.ignore_eos, cancel, lambda text: publish("text", text),
                )
                publish("result", result)
            except Exception:
                logging.exception("Generation failed")
                publish("error", "Model generation failed. See server logs.")

        worker = run_engine(run)
        try:
            while True:
                kind, value = await queue.get()
                yield kind, value
                if kind != "text":
                    break
        finally:
            cancel.set()
            worker.cancel()

    @app.post("/v1/chat/completions")
    async def chat(body: ChatRequest, request: Request):
        if body.model != settings.served_model_name:
            return JSONResponse(error_body(f"Unknown model: {body.model}"), status_code=404)
        output_tokens = body.max_completion_tokens or body.max_tokens or settings.default_output_tokens
        if output_tokens > settings.max_output_tokens:
            return JSONResponse(error_body("Output exceeds --max-output-tokens."), status_code=400)
        messages = normalize(body)
        try:
            prompt = await run_engine(app.state.engine.prepare_prompt, messages)
        except ValueError as exc:
            return JSONResponse(error_body(str(exc)), status_code=400)
        except Exception:
            logging.exception("Tokenizing failed")
            return JSONResponse(error_body("Prompt tokenizing failed.", "server_error"), status_code=500)
        if len(prompt) > settings.max_input_tokens:
            return JSONResponse(
                error_body("Input exceeds --max-input-tokens; prompts are not truncated."),
                status_code=400,
            )
        if len(prompt) + output_tokens > settings.n_ctx:
            return JSONResponse(
                error_body("Input and output tokens exceed --n-ctx; tokens are not truncated."),
                status_code=400,
            )
        metadata = {
            "id": f"chatcmpl-{uuid4().hex}",
            "created": int(time.time()),
            "model": body.model,
        }

        if body.stream:
            async def stream():
                def chunk(delta, finish_reason=None):
                    return {
                        **metadata,
                        "object": "chat.completion.chunk",
                        "choices": [
                            {"index": 0, "delta": delta, "finish_reason": finish_reason}
                        ],
                    }

                yield sse(chunk({"role": "assistant", "content": ""}))
                async with aclosing(events(prompt, body, output_tokens)) as source:
                    async for kind, value in source:
                        if kind == "text":
                            yield sse(chunk({"content": value}))
                        elif kind == "error":
                            yield sse(error_body(value, "server_error"))
                            return
                        else:
                            yield sse(chunk({}, value["finish_reason"]))
                            if body.stream_options and body.stream_options.include_usage:
                                yield sse(
                                    {
                                        **metadata,
                                        "object": "chat.completion.chunk",
                                        "choices": [],
                                        "usage": usage(
                                            value["prompt_tokens"], value["completion_tokens"]
                                        ),
                                    }
                                )
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        cancel = threading.Event()
        task = run_engine(
            app.state.engine.complete, prompt, output_tokens, body.temperature,
            body.top_p, body.ignore_eos, cancel,
        )

        async def disconnected():
            while True:
                if (await request.receive())["type"] == "http.disconnect":
                    return

        disconnect_task = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait(
                {task, disconnect_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if disconnect_task in done:
                return JSONResponse(error_body("Client disconnected."), status_code=499)
            try:
                result = task.result()
            except Exception:
                logging.exception("Generation failed")
                return JSONResponse(
                    error_body("Model generation failed. See server logs.", "server_error"),
                    status_code=500,
                )
            return {
                **metadata,
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": result["text"]},
                        "finish_reason": result["finish_reason"],
                    }
                ],
                "usage": usage(result["prompt_tokens"], result["completion_tokens"]),
            }
        finally:
            cancel.set()
            task.cancel()
            disconnect_task.cancel()
            await asyncio.gather(task, disconnect_task, return_exceptions=True)

    return app


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("/model/model.gguf"))
    parser.add_argument("--served-model-name", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=positive_int, default=8000)
    parser.add_argument("--n-ctx", type=positive_int, default=2048)
    parser.add_argument("--n-batch", type=positive_int, default=512)
    parser.add_argument("--n-threads", type=positive_int, default=4)
    parser.add_argument("--max-input-tokens", type=positive_int, default=2048)
    parser.add_argument("--max-output-tokens", type=positive_int, default=1024)
    parser.add_argument("--default-output-tokens", type=positive_int, default=128)
    args = parser.parse_args()
    if args.default_output_tokens > args.max_output_tokens:
        parser.error("--default-output-tokens must not exceed --max-output-tokens")
    import uvicorn

    settings = Settings(
        model=args.model,
        served_model_name=args.served_model_name,
        n_ctx=args.n_ctx,
        n_batch=args.n_batch,
        n_threads=args.n_threads,
        max_input_tokens=args.max_input_tokens,
        max_output_tokens=args.max_output_tokens,
        default_output_tokens=args.default_output_tokens,
    )
    uvicorn.run(create_app(settings), host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
