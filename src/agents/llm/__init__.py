"""Provider-neutral LLM access. Business code imports `get_router()` and task types from here only."""
from src.agents.llm.errors import LLMError, LLMUnavailable, NoCapableModel  # noqa: F401
from src.agents.llm.providers.anthropic import AnthropicProvider
from src.agents.llm.providers.mock import MockProvider
from src.agents.llm.providers.openai_compat import OpenAICompatibleProvider
from src.agents.llm.registry import ModelRegistry
from src.agents.llm.router import LLMRouter
from src.agents.llm.types import Capability, Message, TaskType  # noqa: F401

_router: LLMRouter | None = None


def build_router(registry: ModelRegistry | None = None) -> LLMRouter:
    from src.agents.limits import llm_quota_ok
    from src.agents.llm.usage import record_model_call

    registry = registry or ModelRegistry.from_settings()
    providers = {"anthropic": AnthropicProvider(), "openai_compatible": OpenAICompatibleProvider(),
                 "mock": MockProvider()}
    return LLMRouter(registry, providers, recorder=record_model_call, quota_check=llm_quota_ok)


def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = build_router()
    return _router


def set_router(router: LLMRouter | None):
    """Replace the process-wide router (application startup and tests)."""
    global _router
    _router = router


async def close_router():
    global _router
    if _router is not None:
        await _router.aclose()
        _router = None
