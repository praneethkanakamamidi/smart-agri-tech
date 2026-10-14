"""LLM router: capability routing, tier ordering, fallback, retries, circuit breaker, structured output."""
import asyncio

import pytest
from pydantic import BaseModel

from src.agents.config import reload_settings
from src.agents.llm.errors import (
    LLMAuthError, LLMBadRequest, LLMQuotaExceeded, LLMServerError, LLMUnavailable, NoCapableModel,
)
from src.agents.llm.providers.mock import MockProvider
from src.agents.llm.registry import ModelConfig, ModelRegistry
from src.agents.llm.router import LLMRouter
from src.agents.llm.types import ImagePart, LLMRequest, Message, RawCompletion, TaskType


class Verdict(BaseModel):
    label: str
    score: float


def model(id_, tier="standard", caps=("text", "structured_output"), **kw):
    return ModelConfig(id=id_, provider="mock", model=f"m-{id_}", tier=tier, capabilities=list(caps), **kw)


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    monkeypatch.setenv("LLM_MAX_RETRIES", "1")
    monkeypatch.setenv("LLM_RETRY_BASE_DELAY_SECONDS", "0")
    monkeypatch.setenv("LLM_CIRCUIT_FAILURES", "2")
    monkeypatch.delenv("LLM_TASK_ROUTES_JSON", raising=False)
    reload_settings()
    yield
    reload_settings()


async def _no_sleep(_):
    return None


def make_router(*configs, **kw):
    provider = MockProvider()
    router = LLMRouter(ModelRegistry(list(configs)), {"mock": provider}, sleep=_no_sleep, **kw)
    return router, provider


def run(coro):
    return asyncio.run(coro)


def text_request(task=TaskType.SUMMARIZATION, schema=None, images=False):
    parts = ["hello"] + ([ImagePart(b"\xff\xd8\xff", "image/jpeg")] if images else [])
    return LLMRequest(task=task, messages=[Message.user(*parts)], output_schema=schema)


def test_prefers_task_tier_then_stronger_then_cheaper():
    router, _ = make_router(model("strong", "strong"), model("fast-b", "fast", input_cost_per_mtok=2),
                            model("fast-a", "fast", input_cost_per_mtok=1), model("std", "standard"))
    order = [m.id for m in router.candidates(text_request(TaskType.INTENT_CLASSIFICATION))]
    assert order == ["fast-a", "fast-b", "std", "strong"]
    order = [m.id for m in router.candidates(text_request(TaskType.DISPUTE_ANALYSIS))]
    assert order[0] == "strong" and order[-1].startswith("fast")


def test_images_only_route_to_vision_models():
    router, _ = make_router(model("text-only", "fast"), model("vision", "strong", caps=("text", "structured_output", "vision")))
    assert [m.id for m in router.candidates(text_request(TaskType.IMAGE_UNDERSTANDING, images=True))] == ["vision"]


def test_no_capable_model_is_an_error_not_a_silent_downgrade():
    router, _ = make_router(model("text-only", "fast"))
    with pytest.raises(NoCapableModel):
        run(router.complete(text_request(TaskType.IMAGE_UNDERSTANDING, images=True)))
    assert router.can_serve(TaskType.IMAGE_UNDERSTANDING, images=True) is False


def test_unavailable_models_are_skipped(monkeypatch):
    monkeypatch.delenv("SOME_MISSING_KEY", raising=False)
    keyed = ModelConfig(id="keyed", provider="openai_compatible", model="x", capabilities=["text"], api_key_env="SOME_MISSING_KEY")
    router, _ = make_router(keyed, model("mock-ok", "fast"))
    router.providers["openai_compatible"] = router.providers["mock"]
    assert [m.id for m in router.candidates(text_request())] == ["mock-ok"]


def test_task_route_override_puts_routed_models_first(monkeypatch):
    monkeypatch.setenv("LLM_TASK_ROUTES_JSON", '{"summarization": ["std"]}')
    reload_settings()
    router, _ = make_router(model("fast", "fast"), model("std", "standard"))
    assert [m.id for m in router.candidates(text_request())] == ["std", "fast"]


def test_retries_then_falls_back_to_next_capable_model():
    router, provider = make_router(model("a", "fast"), model("b", "standard"))
    attempts = []

    def handler(request, spec):
        attempts.append(spec.id)
        return LLMServerError("overloaded") if spec.id == "a" else "fine"

    provider.set_handler("*", handler)
    response = run(router.complete(text_request(TaskType.SUMMARIZATION)))
    assert response.model_id == "b" and response.fallback_rank == 1
    assert attempts == ["a", "a", "b"]  # one retry on the retriable error, then fallback


def test_bad_request_is_not_retried_on_the_same_model():
    router, provider = make_router(model("a", "fast"), model("b", "standard"))
    attempts = []

    def handler(request, spec):
        attempts.append(spec.id)
        return LLMBadRequest("too long") if spec.id == "a" else "ok"

    provider.set_handler("*", handler)
    assert run(router.complete(text_request())).model_id == "b"
    assert attempts == ["a", "b"]


def test_auth_error_opens_the_circuit_immediately():
    router, provider = make_router(model("a", "fast"), model("b", "standard"))
    provider.set_handler("*", lambda r, s: LLMAuthError("bad key") if s.id == "a" else "ok")
    run(router.complete(text_request()))
    assert router.circuit.allow("a") is False
    calls_before = len(provider.calls)
    run(router.complete(text_request()))
    assert all(spec_id == "b" for spec_id, _ in provider.calls[calls_before:])


def test_all_models_failing_raises_unavailable_with_attempts():
    router, provider = make_router(model("a", "fast"))
    provider.set_handler("*", lambda r, s: LLMServerError("down"))
    with pytest.raises(LLMUnavailable) as e:
        run(router.complete(text_request()))
    assert e.value.attempts and e.value.attempts[0]["model_id"] == "a"


def test_structured_output_is_validated_and_repaired_once():
    router, provider = make_router(model("a", "fast"))
    replies = iter(["not json at all", '{"label": "ok", "score": 0.9}'])
    provider.set_handler("*", lambda r, s: RawCompletion(text=next(replies)))
    parsed, response = run(router.structured(TaskType.INTENT_CLASSIFICATION, Verdict, [Message.user("x")]))
    assert parsed == Verdict(label="ok", score=0.9) and response.model_id == "a"
    repair_turn = provider.calls[-1][1].messages
    assert repair_turn[-2].role == "assistant" and "not json" in repair_turn[-2].parts[0].text


def test_invalid_structured_output_falls_back_after_repair():
    router, provider = make_router(model("a", "fast"), model("b", "standard"))
    provider.set_handler("*", lambda r, s: RawCompletion(text='{"label": 1}') if s.id == "a"
                         else {"label": "good", "score": 1})
    parsed, response = run(router.structured(TaskType.INTENT_CLASSIFICATION, Verdict, [Message.user("x")]))
    assert response.model_id == "b" and parsed.label == "good"


def test_timeouts_are_retriable(monkeypatch):
    router, provider = make_router(model("slow", "fast", timeout_s=0.05), model("b", "standard"))

    async def slow(request, spec):
        if spec.id == "slow":
            await asyncio.sleep(5)
        return "ok"

    provider.set_handler("*", slow)
    assert run(router.complete(text_request())).model_id == "b"


def test_quota_check_blocks_before_any_call():
    async def no_quota(user_id):
        return False

    router, provider = make_router(model("a", "fast"), quota_check=no_quota)
    provider.set_handler("*", lambda r, s: "ok")
    request = text_request()
    request.user_id = 5
    with pytest.raises(LLMQuotaExceeded):
        run(router.complete(request))
    assert provider.calls == []


def test_every_call_is_recorded_without_content():
    records = []

    async def recorder(**fields):
        records.append(fields)

    router, provider = make_router(model("a", "fast", input_cost_per_mtok=1.0, output_cost_per_mtok=2.0),
                                   recorder=recorder)
    provider.set_handler("*", lambda r, s: {"label": "x", "score": 1})
    run(router.structured(TaskType.INTENT_CLASSIFICATION, Verdict, [Message.user("secret text")]))
    assert records and records[0]["status"] == "ok" and records[0]["model_id"] == "a"
    assert "secret text" not in str(records)
    assert records[0]["cost_usd"] is not None


def test_registry_rejects_unknown_providers_and_duplicates():
    with pytest.raises(ValueError):
        ModelConfig(id="x", provider="nope", model="m", capabilities=["text"])
    with pytest.raises(ValueError):
        ModelRegistry([model("a"), model("a")])
