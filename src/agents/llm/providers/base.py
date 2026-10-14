"""Provider adapter contract plus the shared HTTP plumbing (timeouts, error classification)."""
import base64
from abc import ABC, abstractmethod

import httpx

from src.agents.llm.errors import LLMBadRequest, LLMConnectionError, LLMTimeout, classify_http_error
from src.agents.llm.registry import ModelSpec
from src.agents.llm.types import LLMRequest, RawCompletion


class Provider(ABC):
    name: str

    @abstractmethod
    async def complete(self, spec: ModelSpec, request: LLMRequest, *, max_tokens: int, temperature: float,
                       timeout_s: float) -> RawCompletion:
        ...

    async def transcribe(self, spec: ModelSpec, audio: bytes, media_type: str, language: str | None,
                         timeout_s: float) -> str:
        raise LLMBadRequest(f"provider '{self.name}' does not support transcription")

    async def aclose(self):
        return None


class HttpProvider(Provider):
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        # One pooled client per provider; tests inject an httpx.MockTransport.
        self._client = httpx.AsyncClient(transport=transport, limits=httpx.Limits(max_connections=20))

    async def _post(self, url: str, *, headers: dict, timeout_s: float, json: dict | None = None,
                    files=None, data=None) -> dict:
        try:
            response = await self._client.post(url, headers=headers, json=json, files=files, data=data,
                                               timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)))
        except httpx.TimeoutException as e:
            raise LLMTimeout(f"{self.name} request timed out") from e
        except httpx.TransportError as e:
            raise LLMConnectionError(f"{self.name} connection failed: {e.__class__.__name__}") from e
        if response.status_code >= 400:
            raise classify_http_error(response.status_code, response.text, response.headers)
        try:
            return response.json()
        except ValueError as e:
            raise LLMBadRequest(f"{self.name} returned a non-JSON response") from e

    async def aclose(self):
        await self._client.aclose()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
