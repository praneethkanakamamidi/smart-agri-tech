"""
Anthropic Messages API adapter (plain HTTP, no SDK).

Structured output uses a forced tool call: the schema becomes the tool's input_schema and the
model must call it, so the result arrives as already-parsed JSON (still validated by the router).
"""
from src.agents.llm.errors import LLMBadRequest, LLMContentFiltered
from src.agents.llm.providers.base import HttpProvider, b64
from src.agents.llm.registry import ModelSpec
from src.agents.llm.structured import json_schema
from src.agents.llm.types import AudioPart, ImagePart, LLMRequest, RawCompletion, TextPart, ToolCall

API_VERSION = "2023-06-01"
DEFAULT_BASE_URL = "https://api.anthropic.com"
RESULT_TOOL = "emit_result"


class AnthropicProvider(HttpProvider):
    name = "anthropic"

    def _headers(self, spec: ModelSpec) -> dict:
        key = spec.api_key()
        if not key:
            raise LLMBadRequest(f"no API key in {spec.api_key_env}")
        return {"x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json",
                **spec.headers}

    @staticmethod
    def _content(parts) -> list[dict]:
        blocks = []
        for part in parts:
            if isinstance(part, TextPart):
                blocks.append({"type": "text", "text": part.text})
            elif isinstance(part, ImagePart):
                blocks.append({"type": "image",
                               "source": {"type": "base64", "media_type": part.media_type, "data": b64(part.data)}})
            elif isinstance(part, AudioPart):
                raise LLMBadRequest("audio parts are not supported by the Anthropic Messages API")
        return blocks

    def build_body(self, spec: ModelSpec, request: LLMRequest, max_tokens: int, temperature: float) -> dict:
        body = {
            "model": spec.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": m.role, "content": self._content(m.parts)} for m in request.messages],
        }
        if request.system:
            body["system"] = request.system
        if request.output_schema is not None and request.tools:
            raise LLMBadRequest("structured output and free tool calling can't be combined in one request")
        if request.output_schema is not None:
            body["tools"] = [{
                "name": RESULT_TOOL,
                "description": "Return the final result. Always call this tool exactly once.",
                "input_schema": json_schema(request.output_schema),
            }]
            body["tool_choice"] = {"type": "tool", "name": RESULT_TOOL}
        elif request.tools:
            body["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters}
                             for t in request.tools]
            if request.tool_choice == "required":
                body["tool_choice"] = {"type": "any"}
            elif request.tool_choice:
                body["tool_choice"] = {"type": "tool", "name": request.tool_choice}
            else:
                body["tool_choice"] = {"type": "auto"}
        return body

    @staticmethod
    def parse(data: dict, structured: bool) -> RawCompletion:
        text_parts, tool_calls, payload = [], [], None
        for block in data.get("content") or []:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                if structured and block.get("name") == RESULT_TOOL:
                    payload = block.get("input")
                else:
                    tool_calls.append(ToolCall(block.get("id", ""), block.get("name", ""), block.get("input") or {}))
        if data.get("stop_reason") == "refusal":
            raise LLMContentFiltered("the model declined the request")
        usage = data.get("usage") or {}
        return RawCompletion(
            text="".join(text_parts), tool_calls=tool_calls, structured=payload,
            input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
            finish_reason=data.get("stop_reason"),
        )

    async def complete(self, spec: ModelSpec, request: LLMRequest, *, max_tokens: int, temperature: float,
                       timeout_s: float) -> RawCompletion:
        base = (spec.base_url or DEFAULT_BASE_URL).rstrip("/")
        data = await self._post(f"{base}/v1/messages", headers=self._headers(spec), timeout_s=timeout_s,
                                json=self.build_body(spec, request, max_tokens, temperature))
        return self.parse(data, structured=request.output_schema is not None)
