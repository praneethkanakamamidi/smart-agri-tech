"""
Optional cross-encoder reranking of a bounded candidate set (RERANKER_ENABLED=true).

Off by default: keep it off unless the retrieval evaluation (python -m evals.run --suites
retrieval) shows it improves NDCG/MRR on your data, because it adds CPU latency per query.
"""
import asyncio
from functools import lru_cache

from src.agents.config import settings


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import CrossEncoder

    cfg = settings()
    return CrossEncoder(cfg.reranker_model, device=cfg.embedding_device)


def _scores(query: str, passages: list[str]) -> list[float]:
    return [float(s) for s in _model().predict([(query, p) for p in passages], show_progress_bar=False)]


async def rerank_scores(query: str, passages: list[str]) -> list[float]:
    return await asyncio.to_thread(_scores, query, passages)
