"""
Scripted provider for deterministic tests and offline evaluation. It is only used when a model
in the registry is configured with provider "mock"; it never stands in for a real model silently.
"""
import inspect
import json
from typing import Callable

from pydantic import BaseModel

from src.agents.llm.errors import LLMBadRequest
from src.agents.llm.providers.base import Provider
from src.agents.llm.registry import ModelSpec
from src.agents.llm.types import LLMRequest, RawCompletion, TextPart

Handler = Callable[[LLMRequest, ModelSpec], object]


class MockProvider(Provider):
    name = "mock"

    def __init__(self):
        self.handlers: dict[str, Handler] = {}
        self.calls: list[tuple[str, LLMRequest]] = []

    def set_handler(self, task: str, handler: Handler):
        """`task` is a TaskType value, "audio_transcription", or "*" for any task."""
        self.handlers[task] = handler

    def clear(self):
        self.handlers.clear()
        self.calls.clear()

    async def _run(self, task: str, request, spec):
        handler = self.handlers.get(task) or self.handlers.get("*")
        if handler is None:
            raise LLMBadRequest(f"mock provider has no scripted response for task '{task}'")
        result = handler(request, spec)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, Exception):
            raise result
        return result

    async def complete(self, spec: ModelSpec, request: LLMRequest, *, max_tokens: int, temperature: float,
                       timeout_s: float) -> RawCompletion:
        self.calls.append((spec.id, request))
        result = await self._run(request.task.value, request, spec)
        if isinstance(result, RawCompletion):
            return result
        if isinstance(result, BaseModel):
            result = result.model_dump(mode="json")
        prompt_chars = sum(len(p.text) for m in request.messages for p in m.parts if isinstance(p, TextPart))
        if isinstance(result, dict):
            text = json.dumps(result)
            return RawCompletion(text=text, structured=result if request.output_schema else None,
                                 input_tokens=prompt_chars // 4, output_tokens=len(text) // 4, finish_reason="stop")
        return RawCompletion(text=str(result), input_tokens=prompt_chars // 4, output_tokens=len(str(result)) // 4,
                             finish_reason="stop")

    async def transcribe(self, spec: ModelSpec, audio: bytes, media_type: str, language: str | None,
                         timeout_s: float) -> str:
        result = await self._run("audio_transcription", (audio, media_type, language), spec)
        return str(result)
