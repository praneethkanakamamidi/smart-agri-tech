"""
Adapter for any OpenAI-compatible Chat Completions endpoint: hosted APIs, and local inference
servers such as Ollama (http://localhost:11434/v1), vLLM or LM Studio.

`structured_mode` on the model config selects how structured output is requested, because
servers differ: json_schema (response_format with a schema), json_object (JSON mode plus the
schema in the prompt) or prompt (schema in the prompt only). The router validates either way.
"""
import json

from src.agents.llm.errors import LLMBadRequest, LLMContentFiltered, LLMOutputInvalid
from src.agents.llm.providers.base import HttpProvider, b64
from src.agents.llm.registry import ModelSpec
from src.agents.llm.structured import json_schema, schema_instructions
from src.agents.llm.types import AudioPart, ImagePart, LLMRequest, RawCompletion, TextPart, ToolCall

AUDIO_FORMATS = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/mp3": "mp3"}


class OpenAICompatibleProvider(HttpProvider):
    name = "openai_compatible"

    def _headers(self, spec: ModelSpec) -> dict:
        headers = {"content-type": "application/json", **spec.headers}
        key = spec.api_key()
        if key:
            headers["authorization"] = f"Bearer {key}"
        elif spec.requires_api_key:
            raise LLMBadRequest(f"no API key in {spec.api_key_env}")
        return headers

    @staticmethod
    def _base(spec: ModelSpec) -> str:
        if not spec.base_url:
            raise LLMBadRequest(f"model '{spec.id}' has no base_url configured")
        return spec.base_url.rstrip("/")

    @staticmethod
    def _content(parts):
        if all(isinstance(p, TextPart) for p in parts):
            return "".join(p.text for p in parts)
        content = []
        for part in parts:
            if isinstance(part, TextPart):
                content.append({"type": "text", "text": part.text})
            elif isinstance(part, ImagePart):
                content.append({"type": "image_url",
                                "image_url": {"url": f"data:{part.media_type};base64,{b64(part.data)}"}})
            elif isinstance(part, AudioPart):
                fmt = AUDIO_FORMATS.get(part.media_type)
                if not fmt:
                    raise LLMBadRequest(f"audio type {part.media_type} is not supported for chat input")
                content.append({"type": "input_audio", "input_audio": {"data": b64(part.data), "format": fmt}})
        return content

    def build_body(self, spec: ModelSpec, request: LLMRequest, max_tokens: int, temperature: float) -> dict:
        mode = spec.structured_mode or "json_schema"
        system = request.system or ""
        if request.output_schema is not None and mode in ("json_object", "prompt"):
            system = (system + "\n\n" + schema_instructions(request.output_schema)).strip()
        messages = [{"role": "system", "content": system}] if system else []
        messages += [{"role": m.role, "content": self._content(m.parts)} for m in request.messages]
        body = {"model": spec.model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        if request.output_schema is not None:
            if request.tools:
                raise LLMBadRequest("structured output and free tool calling can't be combined in one request")
            if mode == "json_schema":
                body["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": request.output_schema.__name__[:64], "schema": json_schema(request.output_schema),
                    "strict": False,
                }}
            elif mode == "json_object":
                body["response_format"] = {"type": "json_object"}
        elif request.tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t.name, "description": t.description, "parameters": t.parameters,
            }} for t in request.tools]
            if request.tool_choice == "required":
                body["tool_choice"] = "required"
            elif request.tool_choice:
                body["tool_choice"] = {"type": "function", "function": {"name": request.tool_choice}}
            else:
                body["tool_choice"] = "auto"
        return body

    @staticmethod
    def parse(data: dict) -> RawCompletion:
        choices = data.get("choices") or []
        if not choices:
            raise LLMOutputInvalid("response had no choices")
        choice = choices[0]
        if choice.get("finish_reason") == "content_filter":
            raise LLMContentFiltered("the response was filtered by the provider")
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        tool_calls = []
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            try:
                arguments = json.loads(fn.get("arguments") or "{}")
            except ValueError as e:
                raise LLMOutputInvalid(f"tool call '{fn.get('name')}' had invalid JSON arguments") from e
            tool_calls.append(ToolCall(call.get("id", ""), fn.get("name", ""), arguments))
        usage = data.get("usage") or {}
        return RawCompletion(
            text=content, tool_calls=tool_calls,
            input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
            finish_reason=choice.get("finish_reason"),
        )

    async def complete(self, spec: ModelSpec, request: LLMRequest, *, max_tokens: int, temperature: float,
                       timeout_s: float) -> RawCompletion:
        data = await self._post(f"{self._base(spec)}/chat/completions", headers=self._headers(spec),
                                timeout_s=timeout_s, json=self.build_body(spec, request, max_tokens, temperature))
        return self.parse(data)

    async def transcribe(self, spec: ModelSpec, audio: bytes, media_type: str, language: str | None,
                         timeout_s: float) -> str:
        headers = {k: v for k, v in self._headers(spec).items() if k != "content-type"}
        extension = media_type.split("/")[-1].replace("mpeg", "mp3").replace("x-wav", "wav")
        data = {"model": spec.model, **({"language": language} if language else {})}
        result = await self._post(
            f"{self._base(spec)}/audio/transcriptions", headers=headers, timeout_s=timeout_s,
            files={"file": (f"audio.{extension}", audio, media_type)}, data=data,
        )
        text = result.get("text")
        if not isinstance(text, str):
            raise LLMOutputInvalid("transcription response had no text")
        return text.strip()
