"""
Model registry. Models, their providers and their capabilities are configuration, never code:

    LLM_PROVIDER=anthropic | openai | local | none   (presets, see src/agents/llm/presets.py)
    LLM_MODELS_FILE=config/llm_models.json      (a full registry; see config/llm_models.example.json)
    LLM_MODELS_JSON='[{"id": "...", ...}]'       (inline full registry; takes precedence over all)

Capabilities are declared by the operator for each model. The router trusts the declaration
for routing and the provider adapter still fails loudly if a model rejects an input.
"""
import json
import os
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

from src.agents.config import settings
from src.agents.llm.types import Capability, Tier
from src.helpers.logging_config import get_logger

logger = get_logger(__name__)

KNOWN_PROVIDERS = {"anthropic", "openai_compatible", "mock"}


class ModelConfig(BaseModel):
    id: str = Field(..., min_length=1, max_length=60, description="Stable routing id, e.g. 'fast-text'.")
    provider: str
    model: str = Field(..., min_length=1, max_length=100, description="Provider model identifier.")
    capabilities: list[Capability]
    tier: Tier = Tier.STANDARD
    base_url: str | None = None
    api_key_env: str | None = Field(None, description="Name of the env var holding the key (never the key).")
    requires_api_key: bool = True
    timeout_s: float | None = None
    max_output_tokens: int | None = None
    context_window: int | None = None
    input_cost_per_mtok: float | None = Field(None, description="USD per million input tokens, if known.")
    output_cost_per_mtok: float | None = None
    enabled: bool = True
    structured_mode: str | None = Field(None, description="openai_compatible: json_schema | json_object | prompt")
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("provider")
    @classmethod
    def known_provider(cls, v: str) -> str:
        if v not in KNOWN_PROVIDERS:
            raise ValueError(f"unknown provider '{v}' (known: {', '.join(sorted(KNOWN_PROVIDERS))})")
        return v


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str
    model: str
    capabilities: frozenset[Capability]
    tier: Tier
    base_url: str | None = None
    api_key_env: str | None = None
    requires_api_key: bool = True
    timeout_s: float | None = None
    max_output_tokens: int | None = None
    context_window: int | None = None
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None
    enabled: bool = True
    structured_mode: str | None = None
    headers: dict = field(default_factory=dict, hash=False, compare=False)

    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env) if self.api_key_env else None

    def available(self) -> bool:
        if not self.enabled:
            return False
        return bool(self.api_key()) if self.requires_api_key else True

    def supports(self, capabilities) -> bool:
        return set(capabilities) <= self.capabilities

    def cost(self, input_tokens: int | None, output_tokens: int | None) -> float | None:
        if self.input_cost_per_mtok is None or self.output_cost_per_mtok is None:
            return None
        if input_tokens is None or output_tokens is None:
            return None
        return round(input_tokens / 1e6 * self.input_cost_per_mtok + output_tokens / 1e6 * self.output_cost_per_mtok, 6)

    def public_view(self) -> dict:
        return {
            "id": self.id, "provider": self.provider, "model": self.model, "tier": self.tier.value,
            "capabilities": sorted(c.value for c in self.capabilities), "enabled": self.enabled,
            "available": self.available(), "api_key_env": self.api_key_env,
            "input_cost_per_mtok": self.input_cost_per_mtok, "output_cost_per_mtok": self.output_cost_per_mtok,
        }


def _spec(config: ModelConfig) -> ModelSpec:
    return ModelSpec(
        id=config.id, provider=config.provider, model=config.model, capabilities=frozenset(config.capabilities),
        tier=config.tier, base_url=config.base_url, api_key_env=config.api_key_env,
        requires_api_key=config.requires_api_key and config.provider != "mock", timeout_s=config.timeout_s,
        max_output_tokens=config.max_output_tokens, context_window=config.context_window,
        input_cost_per_mtok=config.input_cost_per_mtok, output_cost_per_mtok=config.output_cost_per_mtok,
        enabled=config.enabled, structured_mode=config.structured_mode, headers=dict(config.headers),
    )


class ModelRegistry:
    def __init__(self, configs: list[ModelConfig]):
        ids = [c.id for c in configs]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate model ids in registry: {', '.join(sorted(duplicates))}")
        self._models = {c.id: _spec(c) for c in configs}

    @classmethod
    def from_settings(cls) -> "ModelRegistry":
        cfg = settings()
        raw = cfg.models_json
        source = "LLM_MODELS_JSON"
        if raw is None and cfg.models_file:
            with open(cfg.models_file, encoding="utf-8") as fh:
                raw = json.load(fh)
            source = cfg.models_file
        if raw is None:
            from src.agents.llm.presets import models_from_env

            raw = models_from_env()
            source = f"LLM_PROVIDER={cfg.llm_provider}"
        configs = [ModelConfig.model_validate(item) for item in (raw or [])]
        registry = cls(configs)
        logger.info("LLM registry loaded", extra={
            "source": source, "models": [m.id for m in registry.all()],
            "available": [m.id for m in registry.available()],
        })
        return registry

    def all(self) -> list[ModelSpec]:
        return list(self._models.values())

    def available(self) -> list[ModelSpec]:
        return [m for m in self._models.values() if m.available()]

    def get(self, model_id: str) -> ModelSpec | None:
        return self._models.get(model_id)

    def has_capability(self, capability: Capability) -> bool:
        return any(capability in m.capabilities for m in self.available())
