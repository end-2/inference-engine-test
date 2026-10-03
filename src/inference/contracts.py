"""Engine boundaries shared by the HTTP API and feature implementations."""

from concurrent.futures import Executor
from dataclasses import dataclass
import threading
from typing import Any, Callable, Protocol, TypedDict


class GenerationResult(TypedDict):
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int


class CompletionResult(GenerationResult):
    text: str


@dataclass
class Generation:
    prompt: list[int]
    max_tokens: int
    temperature: float
    top_p: float
    ignore_eos: bool
    cancel: threading.Event
    emit: Callable[[str], None] | None = None


class Engine(Protocol):
    def prepare_prompt(self, messages: list[dict]) -> list[int]: ...

    def complete(self, prompt: list[int], max_tokens: int, temperature: float,
                 top_p: float, ignore_eos: bool, cancel: threading.Event) -> CompletionResult: ...

    def stream(self, prompt: list[int], max_tokens: int, temperature: float,
               top_p: float, ignore_eos: bool, cancel: threading.Event,
               emit: Callable[[str], None]) -> GenerationResult: ...

    def close(self) -> None: ...


class ServerSettings(Protocol):
    @property
    def served_model_name(self) -> str: ...

    @property
    def n_ctx(self) -> int: ...

    @property
    def max_input_tokens(self) -> int: ...

    @property
    def max_output_tokens(self) -> int: ...

    @property
    def default_output_tokens(self) -> int: ...

    def engine_settings(self) -> Any: ...

    def create_executor(self) -> Executor: ...
