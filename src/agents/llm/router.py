"""
Task router: picks a capable model for each request, calls it with a timeout and bounded
retries, validates structured output, and falls back to the next *capable* model.

Routing order for a task:
  1. LLM_TASK_ROUTES_JSON override for the task, if any (only capable models are kept), else
  2. models of the task's preferred tier, then stronger tiers, then weaker ones; cheaper first.
A model is never chosen for a request it lacks a capability for (images -> vision, schema ->
structured_output, tools -> tool_calling, audio -> audio). If nothing qualifies the router
raises NoCapableModel instead of quietly degrading.
"""
import asyncio
import random
import time
from typing import Awaitable, Callable

from pydantic import BaseModel

from src.agents.config import settings
from src.agents.llm.circuit import CircuitBreaker
from src.agents.llm.errors import (
    LLMAuthError, LLMError, LLMOutputInvalid, LLMQuotaExceeded, LLMTimeout, LLMUnavailable, NoCapableModel,
)
from src.agents.llm.providers.base import Provider
from src.agents.llm.registry import ModelRegistry, ModelSpec
from src.agents.llm.structured import repair_prompt, validate
from src.agents.llm.types import (
    TASK_PROFILES, TIER_RANK, Capability, LLMRequest, LLMResponse, Message, TaskType, required_capabilities,
)
from src.helpers.logging_config import get_logger

logger = get_logger("agents.llm")

Recorder = Callable[..., Awaitable[None]]
QuotaCheck = Callable[[int], Awaitable[bool]]


async def _no_record(**_):
    return None


class LLMRouter:
    def __init__(self, registry: ModelRegistry, providers: dict[str, Provider], *,
                 recorder: Recorder | None = None, quota_check: QuotaCheck | None = None,
                 circuit: CircuitBreaker | None = None, sleep=asyncio.sleep):
        cfg = settings()
        self.registry = registry
        self.providers = providers
        self.recorder = recorder or _no_record
        self.quota_check = quota_check
        self.circuit = circuit or CircuitBreaker(cfg.circuit_failure_threshold, cfg.circuit_cooldown_s)
        self._sleep = sleep

    # ---- selection --------------------------------------------------------------------------------

    def candidates(self, request: LLMRequest) -> list[ModelSpec]:
        needed = required_capabilities(request)
        capable = [m for m in self.registry.available() if m.supports(needed) and m.provider in self.providers]
        preferred = TIER_RANK[TASK_PROFILES[request.task].tier]

        def key(m: ModelSpec):
            rank = TIER_RANK[m.tier]
            cost = m.input_cost_per_mtok if m.input_cost_per_mtok is not None else float("inf")
            return (rank != preferred, rank < preferred, abs(rank - preferred), cost, m.id)

        ordered = sorted(capable, key=key)
        route = settings().task_routes.get(request.task.value)
        if route:
            # Routed models first, in the configured order; other capable models remain as fallbacks.
            by_id = {m.id: m for m in ordered}
            routed = [by_id[i] for i in route if i in by_id]
            ordered = routed + [m for m in ordered if m.id not in route]
        return ordered

    def can_serve(self, task: TaskType, *, images: bool = False, structured: bool = False, audio: bool = False) -> bool:
        needed = set(TASK_PROFILES[task].capabilities)
        if task != TaskType.AUDIO_TRANSCRIPTION:
            needed.add(Capability.TEXT)
        if images:
            needed.add(Capability.VISION)
        if structured:
            needed.add(Capability.STRUCTURED_OUTPUT)
        if audio:
            needed.add(Capability.AUDIO_INPUT)
        return any(m.supports(needed) and m.provider in self.providers for m in self.registry.available())

    # ---- execution --------------------------------------------------------------------------------

    def _backoff(self, attempt: int, error: LLMError) -> float:
        cfg = settings()
        if error.retry_after:
            return min(error.retry_after, cfg.llm_retry_max_delay_s)
        delay = cfg.llm_retry_base_delay_s * (2 ** attempt)
        return min(delay * (0.5 + random.random()), cfg.llm_retry_max_delay_s)

    async def _record(self, request: LLMRequest, spec: ModelSpec, status: str, *, attempt: int, rank: int,
                      latency_ms: int, error: LLMError | None = None, input_tokens=None, output_tokens=None):
        cost = spec.cost(input_tokens, output_tokens)
        logger.info("llm call", extra={
            "task": request.task.value, "model_id": spec.id, "provider": spec.provider, "model": spec.model,
            "status": status, "attempt": attempt, "fallback_rank": rank, "latency_ms": latency_ms,
            "input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost,
            "error_class": error.code if error else None, "run_id": request.run_id,
        })
        try:
            await self.recorder(
                run_id=request.run_id, user_id=request.user_id, task=request.task.value, provider=spec.provider,
                model=spec.model, model_id=spec.id, status=status, error_class=error.code if error else None,
                attempt=attempt, fallback_rank=rank, latency_ms=latency_ms, input_tokens=input_tokens,
                output_tokens=output_tokens, cost_usd=cost,
            )
        except Exception as e:  # observability must never break a workflow
            logger.warning(f"could not record model call: {e.__class__.__name__}")

    async def _call_once(self, spec: ModelSpec, request: LLMRequest):
        cfg = settings()
        profile = TASK_PROFILES[request.task]
        max_tokens = request.max_output_tokens or spec.max_output_tokens or profile.max_output_tokens
        temperature = profile.temperature if request.temperature is None else request.temperature
        timeout_s = spec.timeout_s or cfg.llm_timeout_s
        provider = self.providers[spec.provider]
        try:
            return await asyncio.wait_for(
                provider.complete(spec, request, max_tokens=max_tokens, temperature=temperature, timeout_s=timeout_s),
                timeout=timeout_s + 2,
            )
        except asyncio.TimeoutError as e:
            raise LLMTimeout(f"{spec.id} did not answer within {timeout_s}s") from e

    async def complete(self, request: LLMRequest) -> LLMResponse:
        if self.quota_check and request.user_id is not None and not await self.quota_check(request.user_id):
            raise LLMQuotaExceeded("hourly model-call quota reached for this user")
        candidates = self.candidates(request)
        if not candidates:
            needed = ", ".join(sorted(c.value for c in required_capabilities(request)))
            raise NoCapableModel(f"no available model supports: {needed} (task {request.task.value})")
        cfg = settings()
        failures: list[dict] = []
        for rank, spec in enumerate(candidates):
            if not self.circuit.allow(spec.id):
                failures.append({"model_id": spec.id, "error": "circuit_open"})
                continue
            working = request
            repaired = False
            attempt = 0
            while attempt <= cfg.llm_max_retries:
                started = time.perf_counter()
                last_output = ""
                try:
                    raw = await self._call_once(spec, working)
                    last_output = raw.text or ("" if raw.structured is None else str(raw.structured))
                    latency = int((time.perf_counter() - started) * 1000)
                    parsed = None
                    if request.output_schema is not None:
                        parsed = validate(request.output_schema, raw.structured if raw.structured is not None else raw.text)
                    self.circuit.record_success(spec.id)
                    await self._record(request, spec, "ok", attempt=attempt, rank=rank, latency_ms=latency,
                                       input_tokens=raw.input_tokens, output_tokens=raw.output_tokens)
                    return LLMResponse(
                        text=raw.text, tool_calls=raw.tool_calls, parsed=parsed, model_id=spec.id,
                        provider=spec.provider, model=spec.model, input_tokens=raw.input_tokens,
                        output_tokens=raw.output_tokens, latency_ms=latency, attempts=attempt + 1,
                        fallback_rank=rank, finish_reason=raw.finish_reason,
                        cost_usd=spec.cost(raw.input_tokens, raw.output_tokens),
                    )
                except LLMOutputInvalid as e:
                    latency = int((time.perf_counter() - started) * 1000)
                    await self._record(request, spec, "error", attempt=attempt, rank=rank, latency_ms=latency, error=e)
                    if repaired or request.output_schema is None:
                        failures.append({"model_id": spec.id, "error": e.code})
                        break
                    # One repair round on the same model (it sees its own reply and the error), then fall back.
                    repaired = True
                    working = LLMRequest(**{**request.__dict__, "messages": request.messages + [
                        Message.assistant(last_output[:4000] or "(no usable output)"), Message.user(repair_prompt(e)),
                    ]})
                except LLMError as e:
                    latency = int((time.perf_counter() - started) * 1000)
                    await self._record(request, spec, "error", attempt=attempt, rank=rank, latency_ms=latency, error=e)
                    if e.opens_circuit:
                        self.circuit.record_failure(spec.id, e.code, immediate=isinstance(e, LLMAuthError))
                    if not e.retriable or attempt >= cfg.llm_max_retries:
                        failures.append({"model_id": spec.id, "error": e.code})
                        break
                    await self._sleep(self._backoff(attempt, e))
                    attempt += 1
        raise LLMUnavailable(f"all capable models failed for task {request.task.value}", failures)

    async def structured(self, task: TaskType, schema: type[BaseModel], messages: list[Message], *,
                         system: str | None = None, run_id: str | None = None, user_id: int | None = None,
                         max_output_tokens: int | None = None) -> tuple[BaseModel, LLMResponse]:
        response = await self.complete(LLMRequest(
            task=task, messages=messages, system=system, output_schema=schema, run_id=run_id, user_id=user_id,
            max_output_tokens=max_output_tokens,
        ))
        return response.parsed, response

    async def transcribe(self, audio: bytes, media_type: str, *, language: str | None = None,
                         run_id: str | None = None, user_id: int | None = None) -> tuple[str, str]:
        request = LLMRequest(task=TaskType.AUDIO_TRANSCRIPTION, messages=[], run_id=run_id, user_id=user_id)
        candidates = self.candidates(request)
        if not candidates:
            raise NoCapableModel("no available model supports audio transcription")
        failures = []
        for rank, spec in enumerate(candidates):
            if not self.circuit.allow(spec.id):
                continue
            started = time.perf_counter()
            try:
                text = await self.providers[spec.provider].transcribe(
                    spec, audio, media_type, language, spec.timeout_s or settings().llm_timeout_s)
                self.circuit.record_success(spec.id)
                await self._record(request, spec, "ok", attempt=0, rank=rank,
                                   latency_ms=int((time.perf_counter() - started) * 1000))
                return text, spec.id
            except LLMError as e:
                await self._record(request, spec, "error", attempt=0, rank=rank,
                                   latency_ms=int((time.perf_counter() - started) * 1000), error=e)
                if e.opens_circuit:
                    self.circuit.record_failure(spec.id, e.code, immediate=isinstance(e, LLMAuthError))
                failures.append({"model_id": spec.id, "error": e.code})
        raise LLMUnavailable("all transcription models failed", failures)

    async def aclose(self):
        for provider in self.providers.values():
            await provider.aclose()
