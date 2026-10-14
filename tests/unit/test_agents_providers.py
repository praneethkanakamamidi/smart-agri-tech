"""Provider adapters: request shape, response parsing and HTTP error classification (no network)."""
import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel

from src.agents.llm.errors import LLMAuthError, LLMContentFiltered, LLMRateLimited, LLMServerError, LLMTimeout
from src.agents.llm.providers.anthropic import AnthropicProvider, RESULT_TOOL
from src.agents.llm.providers.openai_compat import OpenAICompatibleProvider
from src.agents.llm.registry import ModelConfig, _spec
from src.agents.llm.types import ImagePart, LLMRequest, Message, TaskType, ToolSpec


class Out(BaseModel):
    answer: str


def spec(provider, **kw):
    return _spec(ModelConfig(id="m", provider=provider, model="model-x", capabilities=["text", "vision", "structured_output"],
                             api_key_env="TEST_LLM_KEY", **kw))


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("TEST_LLM_KEY", "sk-test")


def run(coro):
    return asyncio.run(coro)


def request(schema=None, image=False, tools=None):
    parts = ["describe"] + ([ImagePart(b"\x89PNGdata", "image/png")] if image else [])
    return LLMRequest(task=TaskType.IMAGE_UNDERSTANDING, messages=[Message.user(*parts)], system="sys",
                      output_schema=schema, tools=tools)


# ---- Anthropic ------------------------------------------------------------------------------------

def test_anthropic_structured_output_uses_a_forced_tool_and_base64_images():
    body = AnthropicProvider().build_body(spec("anthropic"), request(Out, image=True), 500, 0.0)
    assert body["tool_choice"] == {"type": "tool", "name": RESULT_TOOL}
    assert body["tools"][0]["input_schema"]["properties"]["answer"]["type"] == "string"
    image = body["messages"][0]["content"][1]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/png"
    assert body["system"] == "sys"


def test_anthropic_parses_forced_tool_input_and_usage():
    raw = AnthropicProvider.parse({
        "content": [{"type": "tool_use", "id": "t1", "name": RESULT_TOOL, "input": {"answer": "ok"}}],
        "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 3},
    }, structured=True)
    assert raw.structured == {"answer": "ok"} and raw.input_tokens == 10 and raw.tool_calls == []


def test_anthropic_tool_calling_body():
    tools = [ToolSpec("search_listings", "find", {"type": "object", "properties": {}})]
    body = AnthropicProvider().build_body(spec("anthropic"), request(tools=tools), 100, 0.0)
    assert body["tools"][0]["name"] == "search_listings" and body["tool_choice"] == {"type": "auto"}


@pytest.mark.parametrize("status,headers,error", [
    (429, {"retry-after": "3"}, LLMRateLimited),
    (529, {}, LLMServerError),
    (401, {}, LLMAuthError),
    (504, {}, LLMTimeout),
])
def test_anthropic_http_errors_are_classified(status, headers, error):
    seen = {}

    def handler(req: httpx.Request):
        seen.update(req.headers)
        return httpx.Response(status, headers=headers, json={"error": {"type": "x", "message": "nope"}})

    provider = AnthropicProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(error) as e:
        run(provider.complete(spec("anthropic"), request(), max_tokens=10, temperature=0, timeout_s=5))
    assert seen["x-api-key"] == "sk-test" and seen["anthropic-version"]
    if status == 429:
        assert e.value.retry_after == 3.0


def test_anthropic_success_round_trip():
    def handler(req: httpx.Request):
        assert req.url.path == "/v1/messages"
        return httpx.Response(200, json={"content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn",
                                         "usage": {"input_tokens": 1, "output_tokens": 1}})

    provider = AnthropicProvider(transport=httpx.MockTransport(handler))
    raw = run(provider.complete(spec("anthropic"), request(), max_tokens=10, temperature=0, timeout_s=5))
    assert raw.text == "hi"


# ---- OpenAI-compatible -------------------------------------------------------------------------------

def test_openai_compatible_json_schema_and_data_uri_images():
    body = OpenAICompatibleProvider().build_body(spec("openai_compatible", base_url="http://x/v1"),
                                                 request(Out, image=True), 200, 0.0)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"]["properties"]["answer"]
    content = body["messages"][1]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert body["messages"][0] == {"role": "system", "content": "sys"}


def test_openai_compatible_prompt_mode_puts_schema_in_system():
    body = OpenAICompatibleProvider().build_body(
        spec("openai_compatible", base_url="http://x/v1", structured_mode="prompt"), request(Out), 200, 0.0)
    assert "response_format" not in body and "JSON schema" in body["messages"][0]["content"]


def test_openai_compatible_parses_tool_calls_and_filters():
    raw = OpenAICompatibleProvider.parse({"choices": [{"finish_reason": "tool_calls", "message": {
        "content": None, "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": '{"a": 1}'}}]}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2}})
    assert raw.tool_calls[0].arguments == {"a": 1} and raw.output_tokens == 2
    with pytest.raises(LLMContentFiltered):
        OpenAICompatibleProvider.parse({"choices": [{"finish_reason": "content_filter", "message": {}}]})


def test_local_endpoint_without_key_and_transcription():
    def handler(req: httpx.Request):
        assert "authorization" not in req.headers
        assert req.url.path == "/v1/audio/transcriptions"
        assert b"whisper" in req.content
        return httpx.Response(200, json={"text": " 50 kilo tomato "})

    local = _spec(ModelConfig(id="stt", provider="openai_compatible", model="whisper", base_url="http://local/v1",
                              requires_api_key=False, capabilities=["audio_transcription"]))
    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(handler))
    assert run(provider.transcribe(local, b"OggS...", "audio/ogg", None, 5)) == "50 kilo tomato"


def test_transport_timeout_maps_to_llm_timeout():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(LLMTimeout):
        run(provider.complete(spec("openai_compatible", base_url="http://x/v1"), request(), max_tokens=5,
                              temperature=0, timeout_s=1))


def test_error_messages_never_include_the_whole_body():
    def handler(req):
        return httpx.Response(400, text=json.dumps({"error": {"message": "bad", "echo": "PROMPT " * 500}}))

    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(Exception) as e:
        run(provider.complete(spec("openai_compatible", base_url="http://x/v1"), request(), max_tokens=5,
                              temperature=0, timeout_s=1))
    assert "PROMPT" not in str(e.value)
