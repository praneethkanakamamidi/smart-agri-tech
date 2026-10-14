"""
Agent-layer settings, read from the environment once and cached.

Tests change the environment and call `reload_settings()`. Every value has a safe default so
the marketplace runs without any LLM configured (the agents then fall back to deterministic
rules and say so in their responses).
"""
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None or raw == "" else raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


def _json(name: str, default):
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return json.loads(raw)


DEFAULT_RANKING_WEIGHTS = {
    "relevance": 0.35, "price": 0.2, "distance": 0.15, "quantity": 0.15, "trust": 0.1, "freshness": 0.05,
}


@dataclass(frozen=True)
class AgentSettings:
    enabled: bool = True

    # ---- LLM registry and routing
    models_file: str | None = None
    models_json: list | None = None
    task_routes: dict = field(default_factory=dict)  # task -> [model ids in preference order]
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 2
    llm_retry_base_delay_s: float = 0.5
    llm_retry_max_delay_s: float = 8.0
    circuit_failure_threshold: int = 5
    circuit_cooldown_s: float = 60.0
    log_content: bool = False
    llm_responses: bool = True  # let a model phrase final answers (facts are always deterministic)

    # ---- embeddings and retrieval
    embedding_provider: str = "sentence_transformers"  # sentence_transformers | hashing
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_revision: str | None = None
    embedding_query_prefix: str = "query: "
    embedding_passage_prefix: str = "passage: "
    embedding_device: str = "cpu"
    embedding_dim: int = 384  # hashing embedder only
    reranker_enabled: bool = False
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    reranker_top_n: int = 30
    candidate_limit: int = 200
    top_k: int = 10
    rrf_k: int = 60
    ranking_weights: dict = field(default_factory=lambda: dict(DEFAULT_RANKING_WEIGHTS))
    default_radius_km: float = 100.0
    max_radius_km: float = 500.0
    embed_on_demand_limit: int = 50

    # ---- maps / geocoding
    maps_provider: str = "offline"  # offline | osrm
    osrm_base_url: str | None = None
    geocoder_provider: str = "none"  # none | nominatim
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    nominatim_user_agent: str | None = None
    road_distance_factor: float = 1.3
    avg_truck_speed_kmph: float = 35.0
    maps_timeout_s: float = 8.0

    # ---- workflow execution
    checkpointer: str = "postgres"  # postgres | memory (memory = development only, not durable)
    checkpoint_db_url: str | None = None
    checkpoint_schema: str = "langgraph"
    inline_execution: bool = True
    inline_timeout_s: float = 90.0
    lease_s: int = 180
    max_attempts: int = 3
    max_steps: int = 30
    max_negotiation_rounds: int = 5
    approval_ttl_hours: int = 48
    worker_enabled: bool = True
    worker_poll_s: float = 3.0
    worker_batch: int = 5

    # ---- abuse controls
    workflow_starts_per_minute: int = 20
    llm_calls_per_hour: int = 400
    redis_url: str | None = None

    # ---- uploads for multimodal analysis
    vision_max_images: int = 4
    vision_max_edge_px: int = 1568
    audio_max_mb: int = 10

    # ---- retention
    event_retention_days: int = 90
    model_call_retention_days: int = 90
    tool_call_retention_days: int = 365
    unused_image_retention_days: int = 7


@lru_cache(maxsize=1)
def settings() -> AgentSettings:
    return AgentSettings(
        enabled=_bool("AGENTS_ENABLED", True),
        models_file=os.getenv("LLM_MODELS_FILE") or None,
        models_json=_json("LLM_MODELS_JSON", None),
        task_routes=_json("LLM_TASK_ROUTES_JSON", {}),
        llm_timeout_s=_float("LLM_TIMEOUT_SECONDS", 30.0),
        llm_max_retries=_int("LLM_MAX_RETRIES", 2),
        llm_retry_base_delay_s=_float("LLM_RETRY_BASE_DELAY_SECONDS", 0.5),
        llm_retry_max_delay_s=_float("LLM_RETRY_MAX_DELAY_SECONDS", 8.0),
        circuit_failure_threshold=_int("LLM_CIRCUIT_FAILURES", 5),
        circuit_cooldown_s=_float("LLM_CIRCUIT_COOLDOWN_SECONDS", 60.0),
        log_content=_bool("LLM_LOG_CONTENT", False),
        llm_responses=_bool("AGENT_LLM_RESPONSES", True),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "sentence_transformers"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small"),
        embedding_revision=os.getenv("EMBEDDING_MODEL_REVISION") or None,
        embedding_query_prefix=os.getenv("EMBEDDING_QUERY_PREFIX", "query: "),
        embedding_passage_prefix=os.getenv("EMBEDDING_PASSAGE_PREFIX", "passage: "),
        embedding_device=os.getenv("EMBEDDING_DEVICE", "cpu"),
        embedding_dim=_int("EMBEDDING_DIM", 384),
        reranker_enabled=_bool("RERANKER_ENABLED", False),
        reranker_model=os.getenv("RERANKER_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"),
        reranker_top_n=_int("RERANKER_TOP_N", 30),
        candidate_limit=_int("RETRIEVAL_CANDIDATE_LIMIT", 200),
        top_k=_int("RETRIEVAL_TOP_K", 10),
        rrf_k=_int("RETRIEVAL_RRF_K", 60),
        ranking_weights={**DEFAULT_RANKING_WEIGHTS, **_json("RANKING_WEIGHTS_JSON", {})},
        default_radius_km=_float("MATCH_DEFAULT_RADIUS_KM", 100.0),
        max_radius_km=_float("MATCH_MAX_RADIUS_KM", 500.0),
        embed_on_demand_limit=_int("EMBED_ON_DEMAND_LIMIT", 50),
        maps_provider=os.getenv("MAPS_PROVIDER", "offline"),
        osrm_base_url=os.getenv("OSRM_BASE_URL") or None,
        geocoder_provider=os.getenv("GEOCODER_PROVIDER", "none"),
        nominatim_base_url=os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org"),
        nominatim_user_agent=os.getenv("NOMINATIM_USER_AGENT") or None,
        road_distance_factor=_float("ROAD_DISTANCE_FACTOR", 1.3),
        avg_truck_speed_kmph=_float("AVG_TRUCK_SPEED_KMPH", 35.0),
        maps_timeout_s=_float("MAPS_TIMEOUT_SECONDS", 8.0),
        checkpointer=os.getenv("AGENT_CHECKPOINTER", "postgres"),
        checkpoint_db_url=os.getenv("CHECKPOINT_DB_URL") or None,
        checkpoint_schema=os.getenv("CHECKPOINT_SCHEMA", "langgraph"),
        inline_execution=_bool("AGENT_INLINE_EXECUTION", True),
        inline_timeout_s=_float("AGENT_INLINE_TIMEOUT_SECONDS", 90.0),
        lease_s=_int("AGENT_RUN_LEASE_SECONDS", 180),
        max_attempts=_int("AGENT_MAX_ATTEMPTS", 3),
        max_steps=_int("AGENT_MAX_STEPS", 30),
        max_negotiation_rounds=_int("AGENT_MAX_NEGOTIATION_ROUNDS", 5),
        approval_ttl_hours=_int("AGENT_APPROVAL_TTL_HOURS", 48),
        worker_enabled=_bool("AGENT_WORKER_ENABLED", True),
        worker_poll_s=_float("AGENT_WORKER_POLL_SECONDS", 3.0),
        worker_batch=_int("AGENT_WORKER_BATCH", 5),
        workflow_starts_per_minute=_int("AGENT_STARTS_PER_MINUTE", 20),
        llm_calls_per_hour=_int("AGENT_LLM_CALLS_PER_HOUR", 400),
        redis_url=os.getenv("REDIS_URL") or None,
        vision_max_images=_int("VISION_MAX_IMAGES", 4),
        vision_max_edge_px=_int("VISION_MAX_EDGE_PX", 1568),
        audio_max_mb=_int("AUDIO_MAX_MB", 10),
        event_retention_days=_int("AGENT_EVENT_RETENTION_DAYS", 90),
        model_call_retention_days=_int("AGENT_MODEL_CALL_RETENTION_DAYS", 90),
        tool_call_retention_days=_int("AGENT_TOOL_CALL_RETENTION_DAYS", 365),
        unused_image_retention_days=_int("UNUSED_ANALYSIS_IMAGE_RETENTION_DAYS", 7),
    )


def reload_settings() -> AgentSettings:
    settings.cache_clear()
    return settings()
