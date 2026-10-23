"""LLM_PROVIDER presets: anthropic / openai / local / none, overrides, combinations and precedence."""
import pytest

from src.agents.config import reload_settings
from src.agents.llm.presets import models_from_env, selected_providers
from src.agents.llm.registry import ModelRegistry

PROVIDER_VARS = (
    "LLM_PROVIDER", "LLM_MODELS_JSON", "LLM_MODELS_FILE", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL_FAST",
    "ANTHROPIC_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL_STRONG", "OPENAI_TRANSCRIPTION_MODEL",
    "LOCAL_LLM_BASE_URL", "LOCAL_LLM_MODEL", "LOCAL_LLM_VISION_MODEL", "LOCAL_LLM_TOOL_CALLING", "LOCAL_LLM_API_KEY",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in PROVIDER_VARS:
        monkeypatch.delenv(name, raising=False)
    reload_settings()
    yield
    reload_settings()


def set_env(monkeypatch, **values):
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    reload_settings()


def test_default_is_none_and_registers_nothing(monkeypatch):
    assert selected_providers() == ["none"]
    assert models_from_env() == []
    assert ModelRegistry.from_settings().all() == []


def test_anthropic_preset_one_model_per_tier_with_overrides(monkeypatch):
    set_env(monkeypatch, LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL_FAST="claude-custom",
            ANTHROPIC_BASE_URL="https://proxy.example/")
    registry = ModelRegistry.from_settings()
    by_id = {m.id: m for m in registry.all()}
    assert set(by_id) == {"anthropic-fast", "anthropic-standard", "anthropic-strong"}
    assert by_id["anthropic-fast"].model == "claude-custom"
    assert by_id["anthropic-standard"].model == "claude-sonnet-5-5"
    assert by_id["anthropic-strong"].base_url == "https://proxy.example/"
    assert all(m.provider == "anthropic" and m.available() for m in by_id.values())


def test_anthropic_without_key_is_registered_but_unavailable(monkeypatch):
    set_env(monkeypatch, LLM_PROVIDER="anthropic")
    registry = ModelRegistry.from_settings()
    assert len(registry.all()) == 3 and registry.available() == []


def test_openai_preset_includes_transcription(monkeypatch):
    set_env(monkeypatch, LLM_PROVIDER="openai", OPENAI_API_KEY="k", OPENAI_MODEL_STRONG="o-big",
            OPENAI_TRANSCRIPTION_MODEL="whisper-x")
    by_id = {m.id: m for m in ModelRegistry.from_settings().all()}
    assert by_id["openai-strong"].model == "o-big"
    assert by_id["openai-fast"].base_url == "https://api.openai.com/v1"
    assert by_id["openai-fast"].structured_mode == "json_schema"
    assert "audio_transcription" in {c.value for c in by_id["openai-speech-to-text"].capabilities}


def test_local_preset_needs_no_key_and_adds_vision_when_named(monkeypatch):
    set_env(monkeypatch, LLM_PROVIDER="local", LOCAL_LLM_MODEL="qwen2.5", LOCAL_LLM_VISION_MODEL="qwen2.5vl",
            LOCAL_LLM_TOOL_CALLING="true")
    by_id = {m.id: m for m in ModelRegistry.from_settings().all()}
    assert set(by_id) == {"local-fast", "local-standard", "local-strong", "local-vision"}
    assert by_id["local-fast"].base_url == "http://localhost:11434/v1"
    assert all(m.available() and not m.requires_api_key for m in by_id.values())
    caps = {c.value for c in by_id["local-vision"].capabilities}
    assert {"text", "structured_output", "tool_calling", "vision"} <= caps
    assert "vision" not in {c.value for c in by_id["local-standard"].capabilities}


def test_local_preset_with_key(monkeypatch):
    set_env(monkeypatch, LLM_PROVIDER="local", LOCAL_LLM_API_KEY="secret")
    spec = ModelRegistry.from_settings().get("local-fast")
    assert spec.requires_api_key and spec.api_key() == "secret"


def test_providers_can_be_combined_in_order(monkeypatch):
    set_env(monkeypatch, LLM_PROVIDER="anthropic, local", ANTHROPIC_API_KEY="k")
    assert selected_providers() == ["anthropic", "local"]
    ids = [m.id for m in ModelRegistry.from_settings().all()]
    assert ids[:3] == ["anthropic-fast", "anthropic-standard", "anthropic-strong"]
    assert ids[3:] == ["local-fast", "local-standard", "local-strong"]


def test_unknown_provider_is_rejected(monkeypatch):
    set_env(monkeypatch, LLM_PROVIDER="gemini")
    with pytest.raises(ValueError, match="gemini"):
        selected_providers()


def test_full_registry_takes_precedence_over_presets(monkeypatch):
    set_env(monkeypatch, LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="k",
            LLM_MODELS_JSON='[{"id": "only", "provider": "mock", "model": "m", "capabilities": ["text"]}]')
    assert [m.id for m in ModelRegistry.from_settings().all()] == ["only"]
