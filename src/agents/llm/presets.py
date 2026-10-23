"""
Model registry presets chosen by LLM_PROVIDER, for deployments that don't want to write a
registry file. The full registry (LLM_MODELS_FILE / LLM_MODELS_JSON) always takes precedence.

    LLM_PROVIDER=anthropic | openai | local | none      (comma-separated to combine, e.g. "anthropic,local")

anthropic   Claude over the Messages API. ANTHROPIC_API_KEY; ANTHROPIC_MODEL_FAST / _STANDARD /
            _STRONG override the defaults; ANTHROPIC_BASE_URL for a proxy.
openai      OpenAI (or any hosted OpenAI-compatible API). OPENAI_API_KEY, OPENAI_BASE_URL,
            OPENAI_MODEL_FAST / _STANDARD / _STRONG, OPENAI_TRANSCRIPTION_MODEL (speech-to-text).
local       A local OpenAI-compatible server (Ollama, vLLM, LM Studio): LOCAL_LLM_BASE_URL,
            LOCAL_LLM_MODEL, LOCAL_LLM_VISION_MODEL (optional), LOCAL_LLM_STRUCTURED_MODE,
            LOCAL_LLM_TOOL_CALLING, LOCAL_LLM_API_KEY (optional).
none        No models: the agents use their deterministic rules and say so.

Each preset registers one model per tier (fast / standard / strong) so the router's tier
preferences keep working, and the router still falls back across providers when several are
listed. Capabilities below are what the default models support; override the model names if a
chosen model lacks one.
"""
import os

from src.agents.config import settings
from src.helpers.logging_config import get_logger

logger = get_logger(__name__)

PROVIDERS = ("anthropic", "openai", "local", "none")

ANTHROPIC_DEFAULTS = {"fast": "claude-haiku-5-5", "standard": "claude-sonnet-5-5", "strong": "claude-opus-5-5"}
TIER_TIMEOUTS = {"fast": 30, "standard": 60, "strong": 120}
OPENAI_DEFAULTS = {"fast": "gpt-4o-mini", "standard": "gpt-4o", "strong": "gpt-4o"}
OPENAI_BASE_URL = "https://api.openai.com/v1"
LOCAL_BASE_URL = "http://localhost:11434/v1"
LOCAL_DEFAULT_MODEL = "llama3"

TEXT_CAPS = ["text", "structured_output", "tool_calling"]
VISION_CAPS = TEXT_CAPS + ["vision"]


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw in (None, "") else raw.strip().lower() in ("1", "true", "yes", "on")


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def selected_providers() -> list[str]:
    raw = settings().llm_provider or "none"
    chosen = []
    for item in raw.split(","):
        name = item.strip().lower()
        if not name:
            continue
        if name not in PROVIDERS:
            raise ValueError(f"LLM_PROVIDER '{name}' is not one of {', '.join(PROVIDERS)}")
        if name not in chosen:
            chosen.append(name)
    return chosen or ["none"]


def anthropic_models() -> list[dict]:
    base_url = _env("ANTHROPIC_BASE_URL")
    models = []
    for tier, default in ANTHROPIC_DEFAULTS.items():
        models.append({
            "id": f"anthropic-{tier}", "provider": "anthropic",
            "model": _env(f"ANTHROPIC_MODEL_{tier.upper()}", default), "tier": tier,
            "capabilities": VISION_CAPS, "api_key_env": "ANTHROPIC_API_KEY",
            "timeout_s": TIER_TIMEOUTS[tier], **({"base_url": base_url} if base_url else {}),
        })
    return models


def openai_models() -> list[dict]:
    base_url = _env("OPENAI_BASE_URL", OPENAI_BASE_URL)
    models = []
    for tier, default in OPENAI_DEFAULTS.items():
        models.append({
            "id": f"openai-{tier}", "provider": "openai_compatible", "base_url": base_url,
            "model": _env(f"OPENAI_MODEL_{tier.upper()}", default), "tier": tier,
            "capabilities": VISION_CAPS, "api_key_env": "OPENAI_API_KEY",
            "structured_mode": "json_schema", "timeout_s": TIER_TIMEOUTS[tier],
        })
    transcription = _env("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
    if transcription:
        models.append({
            "id": "openai-speech-to-text", "provider": "openai_compatible", "base_url": base_url,
            "model": transcription, "tier": "fast", "capabilities": ["audio_transcription"],
            "api_key_env": "OPENAI_API_KEY", "timeout_s": 60,
        })
    return models


def local_models() -> list[dict]:
    """One local text model serves every tier; a separate vision model is optional."""
    base_url = _env("LOCAL_LLM_BASE_URL", LOCAL_BASE_URL)
    caps = ["text", "structured_output"] + (["tool_calling"] if _bool("LOCAL_LLM_TOOL_CALLING", False) else [])
    common = {
        "provider": "openai_compatible", "base_url": base_url,
        "structured_mode": _env("LOCAL_LLM_STRUCTURED_MODE", "json_schema"),
        "timeout_s": float(_env("LOCAL_LLM_TIMEOUT_SECONDS", "120")),
        # Local servers normally need no key; LOCAL_LLM_API_KEY turns one on.
        **({"api_key_env": "LOCAL_LLM_API_KEY"} if _env("LOCAL_LLM_API_KEY") else {"requires_api_key": False}),
    }
    text_model = _env("LOCAL_LLM_MODEL", LOCAL_DEFAULT_MODEL)
    models = [{"id": f"local-{tier}", "model": text_model, "tier": tier, "capabilities": caps, **common}
              for tier in ("fast", "standard", "strong")]
    vision_model = _env("LOCAL_LLM_VISION_MODEL")
    if vision_model:
        models.append({"id": "local-vision", "model": vision_model, "tier": "standard",
                       "capabilities": caps + ["vision"], **common})
    return models


BUILDERS = {"anthropic": anthropic_models, "openai": openai_models, "local": local_models}


def models_from_env() -> list[dict]:
    """Model configs for the providers named in LLM_PROVIDER (empty for 'none')."""
    models = []
    for provider in selected_providers():
        if provider == "none":
            continue
        models.extend(BUILDERS[provider]())
    missing = sorted({m["api_key_env"] for m in models
                      if m.get("api_key_env") and m.get("requires_api_key", True) and not os.getenv(m["api_key_env"])})
    if missing:
        logger.warning(f"LLM_PROVIDER models need an API key: set {', '.join(missing)}")
    return models
