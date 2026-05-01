"""
CPU cross-encoder reranker.

Uses sentence-transformers CrossEncoder (ms-marco-MiniLM-L-6-v2, ~22 MB) to
produce precise query-document relevance scores.  The model is loaded lazily
on first use and runs entirely on CPU in a thread-pool executor so it never
blocks the async event loop and never competes with the GPU.

Global standard pattern:
  hybrid retrieval (vector + BM25 + lexical rerank)
  → cross-encoder rerank          ← this module
  → multi-signal confidence gate  ← socket_handlers._extract_kb_prefetch_payload
  → LLM                           ← core.run_agent_loop_with_emitter
"""

from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

# Model name — small, fast, accurate for passage reranking.
# Downloaded once by sentence-transformers and cached in ~/.cache/torch/
_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@lru_cache(maxsize=1)
def _load_cross_encoder():
    """Lazy-load and cache the cross-encoder model (once per process)."""
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
        logger.info("[reranker] Loading cross-encoder model: %s", _CROSS_ENCODER_MODEL)
        model = CrossEncoder(_CROSS_ENCODER_MODEL)
        logger.info("[reranker] Cross-encoder model loaded successfully")
        return model
    except ImportError:
        logger.warning(
            "[reranker] sentence-transformers not installed — reranker disabled. "
            "Run: pip install sentence-transformers"
        )
        return None
    except Exception as exc:
        logger.warning("[reranker] Failed to load cross-encoder: %s", exc)
        return None


def _rerank_sync(query: str, sources: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """
    Synchronous rerank — called in a thread executor.
    Adds 'reranker_score' (float, higher = more relevant) to each source.
    Returns top_k sources sorted by reranker_score descending.
    """
    model = _load_cross_encoder()
    if model is None:
        # Reranker unavailable — return as-is with score=0.0
        for s in sources:
            s.setdefault("reranker_score", 0.0)
        return sources[:top_k]

    pairs = [(query, s.get("content_text") or s.get("document_title") or "") for s in sources]
    try:
        scores: list[float] = model.predict(pairs).tolist()
    except Exception as exc:
        logger.warning("[reranker] predict failed: %s — returning unranked", exc)
        for s in sources:
            s.setdefault("reranker_score", 0.0)
        return sources[:top_k]

    for source, score in zip(sources, scores):
        source["reranker_score"] = float(score)

    sources_sorted = sorted(sources, key=lambda s: s["reranker_score"], reverse=True)
    return sources_sorted[:top_k]


async def rerank(
    query: str,
    sources: list[dict[str, Any]],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    Async wrapper — runs _rerank_sync in the default executor (thread pool).
    Returns top_k sources with 'reranker_score' field added, sorted best-first.
    If reranker is unavailable, returns sources unchanged (with score=0.0).
    """
    if not sources:
        return sources

    started = time.perf_counter()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _rerank_sync, query, list(sources), top_k)
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "[reranker] reranked query=%r results=%d->%d elapsed_ms=%.0f top_score=%.3f",
        query[:60],
        len(sources),
        len(result),
        elapsed_ms,
        result[0].get("reranker_score", 0.0) if result else 0.0,
    )
    return result
