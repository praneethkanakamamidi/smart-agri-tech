"""Provider-neutral request/response types, capabilities and task profiles."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


class Capability(str, Enum):
    TEXT = "text"
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_CALLING = "tool_calling"
    VISION = "vision"
    AUDIO_INPUT = "audio_input"  # audio parts inside a chat request
    AUDIO_TRANSCRIPTION = "audio_transcription"  # dedicated speech-to-text endpoint
    STREAMING = "streaming"


class Tier(str, Enum):
    FAST = "fast"  # cheap, low latency: classification, extraction, short summaries
    STANDARD = "standard"
    STRONG = "strong"  # hardest reasoning: planning, dispute analysis


TIER_RANK = {Tier.FAST: 0, Tier.STANDARD: 1, Tier.STRONG: 2}


class TaskType(str, Enum):
    INTENT_CLASSIFICATION = "intent_classification"
    ENTITY_EXTRACTION = "entity_extraction"
    QUERY_REWRITE = "query_rewrite"
    PLANNING = "planning"
    NEGOTIATION = "negotiation"
    IMAGE_UNDERSTANDING = "image_understanding"
    AUDIO_TRANSCRIPTION = "audio_transcription"
    DISPUTE_ANALYSIS = "dispute_analysis"
    SUMMARIZATION = "summarization"


@dataclass(frozen=True)
class TaskProfile:
    capabilities: frozenset[Capability]
    tier: Tier
    max_output_tokens: int
    temperature: float = 0.0


TASK_PROFILES: dict[TaskType, TaskProfile] = {
    TaskType.INTENT_CLASSIFICATION: TaskProfile(frozenset({Capability.TEXT}), Tier.FAST, 600),
    TaskType.ENTITY_EXTRACTION: TaskProfile(frozenset({Capability.TEXT}), Tier.FAST, 800),
    TaskType.QUERY_REWRITE: TaskProfile(frozenset({Capability.TEXT}), Tier.FAST, 300),
    TaskType.PLANNING: TaskProfile(frozenset({Capability.TEXT}), Tier.STRONG, 1500),
    TaskType.NEGOTIATION: TaskProfile(frozenset({Capability.TEXT}), Tier.STANDARD, 800, 0.2),
    TaskType.IMAGE_UNDERSTANDING: TaskProfile(frozenset({Capability.VISION}), Tier.STANDARD, 1500),
    TaskType.AUDIO_TRANSCRIPTION: TaskProfile(frozenset({Capability.AUDIO_TRANSCRIPTION}), Tier.FAST, 0),
    TaskType.DISPUTE_ANALYSIS: TaskProfile(frozenset({Capability.TEXT}), Tier.STRONG, 2500),
    TaskType.SUMMARIZATION: TaskProfile(frozenset({Capability.TEXT}), Tier.FAST, 600, 0.2),
}


@dataclass
class TextPart:
    text: str
    type: Literal["text"] = "text"


@dataclass
class ImagePart:
    data: bytes
    media_type: str  # image/jpeg | image/png | image/webp
    type: Literal["image"] = "image"


@dataclass
class AudioPart:
    data: bytes
    media_type: str
    type: Literal["audio"] = "audio"


Part = TextPart | ImagePart | AudioPart


@dataclass
class Message:
    role: Literal["user", "assistant"]
    parts: list[Part]

    @classmethod
    def user(cls, *parts: Part | str) -> "Message":
        return cls("user", [TextPart(p) if isinstance(p, str) else p for p in parts])

    @classmethod
    def assistant(cls, text: str) -> "Message":
        return cls("assistant", [TextPart(text)])


@dataclass
class ToolSpec:
    """A function the model may call. Execution always goes through the agent tool layer."""
    name: str
    description: str
    parameters: dict  # JSON schema


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMRequest:
    task: TaskType
    messages: list[Message]
    system: str | None = None
    output_schema: type[BaseModel] | None = None  # structured output, validated with pydantic
    tools: list[ToolSpec] | None = None
    tool_choice: str | None = None  # None = auto, "required", or a tool name
    max_output_tokens: int | None = None
    temperature: float | None = None
    # Observability / quota attribution only. Never used for authorization.
    run_id: str | None = None
    user_id: int | None = None

    def has_images(self) -> bool:
        return any(isinstance(p, ImagePart) for m in self.messages for p in m.parts)

    def has_audio(self) -> bool:
        return any(isinstance(p, AudioPart) for m in self.messages for p in m.parts)


@dataclass
class RawCompletion:
    """What a provider adapter returns; the router adds routing metadata."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    structured: Any = None  # provider-native structured payload (e.g. forced tool input)
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    parsed: BaseModel | None
    model_id: str
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    attempts: int
    fallback_rank: int  # 0 = first choice
    finish_reason: str | None = None
    cost_usd: float | None = None


def required_capabilities(request: LLMRequest) -> frozenset[Capability]:
    caps = set(TASK_PROFILES[request.task].capabilities)
    if request.has_images():
        caps.add(Capability.VISION)
    if request.has_audio():
        caps.add(Capability.AUDIO_INPUT)
    if request.output_schema is not None:
        caps.add(Capability.STRUCTURED_OUTPUT)
    if request.tools:
        caps.add(Capability.TOOL_CALLING)
    if request.task != TaskType.AUDIO_TRANSCRIPTION:
        caps.add(Capability.TEXT)
    return frozenset(caps)
