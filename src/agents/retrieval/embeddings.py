"""
Text embedders. Vectors are always L2-normalised so cosine similarity == dot product and
pgvector's cosine distance (<=>) ranks consistently whatever the model.

- SentenceTransformerEmbedder (default): EMBEDDING_MODEL, multilingual by default
  (intfloat/multilingual-e5-small) because the marketplace serves Telugu, Hindi-in-Latin-script
  and English text. E5 models expect "query: " / "passage: " prefixes; set the
  EMBEDDING_*_PREFIX variables to "" for models that don't.
- HashingEmbedder: deterministic feature hashing, no download. For tests, CI and development
  only - it captures character overlap, not meaning.

`model_version` identifies the vector space. Stored embeddings are keyed by it, so changing the
model (or its prefixes/revision) means a re-index rather than mixing incompatible vectors.
"""
import asyncio
import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

from src.agents.config import settings

_WORD = re.compile(r"\w+", re.UNICODE)


class Embedder(Protocol):
    model_version: str
    dimensions: int

    def embed_queries(self, texts: list[str]) -> list[list[float]]: ...

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...


def l2_normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm > 0 else vector


class HashingEmbedder:
    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions
        self.model_version = f"hashing-v1:{dimensions}"

    def _features(self, text: str) -> list[str]:
        words = [w.lower() for w in _WORD.findall(text or "")]
        features = [f"w:{w}" for w in words]
        for w in words:
            padded = f"<{w}>"
            features += [f"c:{padded[i:i + 3]}" for i in range(max(1, len(padded) - 2))]
        return features

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for feature in self._features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign * (1.0 if feature.startswith("w:") else 0.5)
        return l2_normalise(vector)

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, *, revision: str | None, device: str, query_prefix: str, passage_prefix: str):
        self.model_name = model_name
        self.revision = revision
        self.device = device
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix
        self._model = None
        prefix_tag = hashlib.sha1(f"{query_prefix}|{passage_prefix}".encode()).hexdigest()[:6]
        self.model_version = f"st:{model_name}@{revision or 'default'}:{prefix_tag}"
        self._dimensions: int | None = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise RuntimeError(
                    "EMBEDDING_PROVIDER=sentence_transformers needs `pip install -r requirements-ml.txt`."
                ) from e
            self._model = SentenceTransformer(self.model_name, revision=self.revision, device=self.device)
            self._dimensions = int(self._model.get_sentence_embedding_dimension())
        return self._model

    @property
    def dimensions(self) -> int:
        if self._dimensions is None:
            self._load()
        return self._dimensions

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._load().encode(texts, batch_size=32, normalize_embeddings=True, convert_to_numpy=True,
                                      show_progress_bar=False)
        return [v.tolist() for v in vectors]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._encode([self.query_prefix + t for t in texts])

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._encode([self.passage_prefix + t for t in texts])


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    cfg = settings()
    if cfg.embedding_provider == "hashing":
        return HashingEmbedder(cfg.embedding_dim)
    if cfg.embedding_provider == "sentence_transformers":
        return SentenceTransformerEmbedder(
            cfg.embedding_model, revision=cfg.embedding_revision, device=cfg.embedding_device,
            query_prefix=cfg.embedding_query_prefix, passage_prefix=cfg.embedding_passage_prefix,
        )
    raise ValueError(f"unknown EMBEDDING_PROVIDER '{cfg.embedding_provider}'")


async def embed_queries(texts: list[str]) -> list[list[float]]:
    # Model inference is CPU-bound; keep it off the event loop.
    return await asyncio.to_thread(get_embedder().embed_queries, texts)


async def embed_passages(texts: list[str]) -> list[list[float]]:
    return await asyncio.to_thread(get_embedder().embed_passages, texts)


def vector_literal(vector: list[float]) -> str:
    """pgvector text format, bound as a plain string and cast in SQL (no driver codec needed)."""
    return "[" + ",".join(f"{v:.7f}" for v in vector) + "]"
