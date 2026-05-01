# Tool: search_banking_knowledge — PgVector RAG for banking help
import asyncio
import json
import logging
import re
import time
from collections import OrderedDict

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, literal, or_, text
from sqlalchemy.future import select

from app.config import settings
from app.tools.base import register_tool

logger = logging.getLogger(__name__)

# Keep embedding calls fast and resilient under Ollama instability.
_EMBED_ATTEMPTS = max(1, int(settings.embedding_attempts))
_EMBED_BACKOFF_SECONDS = 0.35
_EMBED_TIMEOUT_SECONDS = max(0.5, float(settings.embedding_timeout_ms) / 1000.0)
_EMBED_TIMEOUT = httpx.Timeout(
    connect=min(1.0, _EMBED_TIMEOUT_SECONDS),
    read=_EMBED_TIMEOUT_SECONDS,
    write=_EMBED_TIMEOUT_SECONDS,
    pool=min(1.0, _EMBED_TIMEOUT_SECONDS),
)
# Slow timeout for retry attempts: covers Ollama model-swap time.
# When qwen/granite finishes and Ollama swaps to the embedding model it takes
# 3-15 s.  25 s gives comfortable headroom without blocking the request.
_EMBED_TIMEOUT_SLOW = httpx.Timeout(connect=3.0, read=25.0, write=25.0, pool=3.0)
_ENDPOINT_COOLDOWN_SECONDS = 45.0
_ENDPOINT_FAILURE_UNTIL: dict[str, float] = {}
_EMBED_SEMAPHORE = asyncio.Semaphore(1)
_BREAKER_OPEN_UNTIL = 0.0
_BREAKER_FAILURE_STREAK = 0
_EMBED_CACHE: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()
_NON_RETRYABLE_STATUS_CODES = {400, 404, 405, 422, 501}


def embedding_backend_degraded() -> bool:
    return time.monotonic() < _BREAKER_OPEN_UNTIL


def _record_embedding_success() -> None:
    global _BREAKER_FAILURE_STREAK, _BREAKER_OPEN_UNTIL
    _BREAKER_FAILURE_STREAK = 0
    _BREAKER_OPEN_UNTIL = 0.0


def _record_embedding_failure() -> None:
    global _BREAKER_FAILURE_STREAK, _BREAKER_OPEN_UNTIL
    _BREAKER_FAILURE_STREAK += 1
    threshold = max(1, int(settings.embedding_breaker_failure_threshold))
    if _BREAKER_FAILURE_STREAK >= threshold:
        _BREAKER_OPEN_UNTIL = time.monotonic() + max(1, int(settings.embedding_breaker_cooldown_seconds))
        logger.warning(
            "Embedding breaker opened for %ss after %d consecutive failures",
            int(settings.embedding_breaker_cooldown_seconds),
            _BREAKER_FAILURE_STREAK,
        )


def _embedding_cache_key(query_text: str) -> str:
    return f"{settings.embedding_model}::{query_text.strip().lower()}"


def _get_cached_embedding(query_text: str) -> list[float] | None:
    ttl = max(1, int(settings.embedding_cache_ttl_seconds))
    now = time.monotonic()
    key = _embedding_cache_key(query_text)
    item = _EMBED_CACHE.get(key)
    if item is None:
        return None
    created_at, emb = item
    if now - created_at > ttl:
        _EMBED_CACHE.pop(key, None)
        return None
    _EMBED_CACHE.move_to_end(key)
    return emb


def _put_cached_embedding(query_text: str, embedding: list[float]) -> None:
    key = _embedding_cache_key(query_text)
    _EMBED_CACHE[key] = (time.monotonic(), embedding)
    _EMBED_CACHE.move_to_end(key)
    max_entries = max(32, int(settings.embedding_cache_max_entries))
    while len(_EMBED_CACHE) > max_entries:
        _EMBED_CACHE.popitem(last=False)


async def _sparse_search_rows(args: "VectorSearchInput"):
    from app.db.connection import AsyncSessionLocal
    from app.db.models import BankingKnowledge, KnowledgeDocument
    candidate_k = max(args.top_k, args.top_k * max(1, int(settings.sparse_candidate_multiplier)))

    fb_started = time.perf_counter()
    async with AsyncSessionLocal() as session:
        tsv_text = func.concat(
            func.coalesce(BankingKnowledge.document_title, ""),
            " ",
            func.coalesce(BankingKnowledge.content_text, ""),
        )
        tsv = func.to_tsvector("simple", tsv_text)
        tsq = func.websearch_to_tsquery("simple", args.query)
        sparse_score = func.ts_rank_cd(tsv, tsq).label("sparse_score")
        filters = _build_filters(args, include_language=True)
        filters.append(tsv.op("@@")(tsq))

        sparse_stmt = (
            select(BankingKnowledge, sparse_score)
            .join(KnowledgeDocument, BankingKnowledge.document_id == KnowledgeDocument.id)
            .where(*filters)
            .order_by(desc(sparse_score), desc(BankingKnowledge.updated_at))
            .limit(candidate_k)
        )
        sparse_result = await session.execute(sparse_stmt)
        rows = sparse_result.all()

        if not rows and args.language:
            fallback_filters = _build_filters(args, include_language=False)
            fallback_filters.append(tsv.op("@@")(tsq))
            fallback_stmt = (
                select(BankingKnowledge, sparse_score)
                .join(KnowledgeDocument, BankingKnowledge.document_id == KnowledgeDocument.id)
                .where(*fallback_filters)
                .order_by(desc(sparse_score), desc(BankingKnowledge.updated_at))
                .limit(candidate_k)
            )
            fallback_result = await session.execute(fallback_stmt)
            rows = fallback_result.all()

        if not rows:
            keywords = [t for t in re.findall(r"[A-Za-z0-9]+", args.query) if len(t) >= 2][:8]
            if keywords:
                relaxed_filters = _build_filters(args, include_language=False)
                relaxed_filters.append(
                    or_(*(
                        BankingKnowledge.document_title.ilike(f"%{kw}%") |
                        BankingKnowledge.content_text.ilike(f"%{kw}%")
                        for kw in keywords
                    ))
                )
                relaxed_stmt = (
                    select(BankingKnowledge, literal(0.0).label("sparse_score"))
                    .join(KnowledgeDocument, BankingKnowledge.document_id == KnowledgeDocument.id)
                    .where(*relaxed_filters)
                    .order_by(desc(BankingKnowledge.updated_at))
                    .limit(candidate_k)
                )
                relaxed_result = await session.execute(relaxed_stmt)
                rows = relaxed_result.all()
    logger.info(
        "KB sparse search elapsed_ms=%.0f rows=%d",
        (time.perf_counter() - fb_started) * 1000,
        len(rows),
    )
    return rows


async def _dense_search_rows(args: "VectorSearchInput", embedding: list[float]):
    from app.db.connection import AsyncSessionLocal
    from app.db.models import BankingKnowledge, KnowledgeDocument

    candidate_k = max(args.top_k, args.top_k * max(1, int(settings.vector_candidate_multiplier)))
    min_similarity = max(0.0, min(1.0, float(settings.hybrid_min_dense_similarity)))
    max_distance = 1.0 - min_similarity

    dense_started = time.perf_counter()
    async with AsyncSessionLocal() as session:
        await session.execute(text(f"SET LOCAL hnsw.ef_search = {max(20, int(settings.vector_hnsw_ef_search))}"))
        distance_expr = BankingKnowledge.chunk_embedding.cosine_distance(embedding).label("dense_distance")
        filters = _build_filters(args, include_language=True)
        filters.extend([
            BankingKnowledge.chunk_embedding.isnot(None),
            distance_expr <= max_distance,
        ])
        dense_stmt = (
            select(BankingKnowledge, distance_expr)
            .join(KnowledgeDocument, BankingKnowledge.document_id == KnowledgeDocument.id)
            .where(*filters)
            .order_by(distance_expr)
            .limit(candidate_k)
        )
        dense_result = await session.execute(dense_stmt)
        rows = dense_result.all()

        if not rows and args.language:
            relaxed_filters = _build_filters(args, include_language=False)
            relaxed_filters.extend([
                BankingKnowledge.chunk_embedding.isnot(None),
                distance_expr <= max_distance,
            ])
            relaxed_stmt = (
                select(BankingKnowledge, distance_expr)
                .join(KnowledgeDocument, BankingKnowledge.document_id == KnowledgeDocument.id)
                .where(*relaxed_filters)
                .order_by(distance_expr)
                .limit(candidate_k)
            )
            relaxed_result = await session.execute(relaxed_stmt)
            rows = relaxed_result.all()

    logger.info(
        "KB dense search elapsed_ms=%.0f rows=%d",
        (time.perf_counter() - dense_started) * 1000,
        len(rows),
    )
    return rows


def _fuse_hybrid_results(dense_hits: list[tuple], sparse_hits: list[tuple], top_k: int):
    dense_weight = max(0.0, float(settings.hybrid_dense_weight))
    sparse_weight = max(0.0, float(settings.hybrid_sparse_weight))
    if dense_weight == 0.0 and sparse_weight == 0.0:
        dense_weight = 1.0
    rrf_k = max(1, int(settings.hybrid_rrf_k))

    fused: dict[str, dict] = {}

    for rank, (row, dense_distance) in enumerate(dense_hits, start=1):
        rid = str(row.id)
        entry = fused.get(rid)
        if entry is None:
            entry = {
                "row": row,
                "score": 0.0,
                "dense_rank": 10**9,
                "sparse_rank": 10**9,
                "dense_distance": 1.0,
            }
            fused[rid] = entry
        entry["score"] += dense_weight / (rrf_k + rank)
        entry["dense_rank"] = rank
        entry["dense_distance"] = float(dense_distance)

    for rank, (row, _sparse_score) in enumerate(sparse_hits, start=1):
        rid = str(row.id)
        entry = fused.get(rid)
        if entry is None:
            entry = {
                "row": row,
                "score": 0.0,
                "dense_rank": 10**9,
                "sparse_rank": 10**9,
                "dense_distance": 1.0,
            }
            fused[rid] = entry
        entry["score"] += sparse_weight / (rrf_k + rank)
        entry["sparse_rank"] = rank

    ranked = sorted(
        fused.values(),
        key=lambda e: (
            -e["score"],
            e["dense_rank"],
            e["sparse_rank"],
            e["dense_distance"],
        ),
    )
    return [item["row"] for item in ranked[:top_k]]


def _tokenize(text_value: str) -> set[str]:
    return {t for t in re.findall(r"\w+", (text_value or "").lower()) if len(t) > 1}


def _rerank_fused_rows(query: str, rows: list, top_k: int):
    if not rows:
        return rows

    query_tokens = _tokenize(query)
    lexical_boost = max(0.0, float(settings.hybrid_lexical_boost))
    max_chunks_per_doc = max(1, int(settings.hybrid_max_chunks_per_document))

    rescored = []
    query_lc = (query or "").lower()
    for idx, row in enumerate(rows, start=1):
        title_text = row.document_title or ""
        content_text = row.content_text or ""
        title_tokens = _tokenize(title_text)
        text_tokens = _tokenize(f"{title_text} {content_text}")
        overlap = 0.0
        title_overlap = 0.0
        if query_tokens:
            overlap = len(query_tokens & text_tokens) / max(1, len(query_tokens))
            title_overlap = len(query_tokens & title_tokens) / max(1, len(query_tokens))
        phrase_boost = 0.15 if query_lc and query_lc in title_text.lower() else 0.0
        base = 1.0 / (idx + 1)
        rescored.append((row, base + (lexical_boost * overlap) + (0.25 * title_overlap) + phrase_boost))

    rescored.sort(key=lambda item: item[1], reverse=True)

    selected = []
    per_doc_count: dict[str, int] = {}
    for row, _score in rescored:
        doc_id = str(row.document_id) if row.document_id is not None else str(row.id)
        used = per_doc_count.get(doc_id, 0)
        if used >= max_chunks_per_doc:
            continue
        per_doc_count[doc_id] = used + 1
        selected.append(row)
        if len(selected) >= top_k:
            break

    return selected


def _is_endpoint_on_cooldown(endpoint: str) -> bool:
    return _ENDPOINT_FAILURE_UNTIL.get(endpoint, 0.0) > time.monotonic()


def _mark_endpoint_failed(endpoint: str) -> None:
    _ENDPOINT_FAILURE_UNTIL[endpoint] = time.monotonic() + _ENDPOINT_COOLDOWN_SECONDS


def _mark_endpoint_healthy(endpoint: str) -> None:
    _ENDPOINT_FAILURE_UNTIL.pop(endpoint, None)


def _is_non_retryable_embedding_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _NON_RETRYABLE_STATUS_CODES
    return False


class VectorSearchInput(BaseModel):
    query: str = Field(..., description="User's banking question")
    top_k: int = Field(5, description="Number of results to return", ge=1, le=20)
    language: str | None = Field(None, description="Optional language filter, e.g. 'en' or 'bn'")
    document_type: str | None = Field(None, description="Optional document type filter")
    category: str | None = Field(None, description="Optional document category filter")
    intent_tags: list[str] | None = Field(None, description="Optional intent tags filter")


def _build_filters(args: VectorSearchInput, *, include_language: bool = True):
    from app.db.models import BankingKnowledge, KnowledgeDocument

    filters = [
        KnowledgeDocument.is_published == True,
        BankingKnowledge.is_active == True,
    ]

    if include_language and args.language:
        filters.append(BankingKnowledge.language == args.language)
    if args.document_type:
        filters.append(BankingKnowledge.document_type == args.document_type)
    if args.category:
        filters.append(KnowledgeDocument.category == args.category)
    if args.intent_tags:
        filters.append(KnowledgeDocument.intent_tags.overlap(args.intent_tags))

    return filters


async def embed_query(query_text: str) -> list[float]:
    """Embed a text string with retry and endpoint fallback for Ollama."""
    if embedding_backend_degraded():
        raise RuntimeError("Embedding backend circuit breaker is open")

    cached = _get_cached_embedding(query_text)
    if cached is not None:
        logger.debug("Embedding cache hit query_len=%d", len(query_text))
        return cached

    last_exc: Exception | None = None

    async with _EMBED_SEMAPHORE:
        for attempt in range(1, _EMBED_ATTEMPTS + 1):
            # Attempt 1: fast timeout — model is already hot (~200 ms).
            # Attempt 2+: slow timeout — covers Ollama model-swap time (3-15 s).
            # Both /api/embeddings and /api/embed serve the same Ollama instance,
            # so a timeout on one means the other will also time out.  We break
            # after the first timeout instead of wasting time on the second endpoint.
            is_retry = attempt > 1
            timeout = _EMBED_TIMEOUT_SLOW if is_retry else _EMBED_TIMEOUT
            if is_retry:
                logger.info(
                    "Embedding retry attempt=%d using extended timeout=%.0fs (model-swap wait)",
                    attempt, timeout.read,
                )

            endpoint_payloads = [
                ("/api/embeddings", {"model": settings.embedding_model, "prompt": query_text}),
                ("/api/embed", {"model": settings.embedding_model, "input": query_text}),
            ]

            async with httpx.AsyncClient(timeout=timeout) as client:
                attempted_any = False
                timed_out = False
                for endpoint, payload in endpoint_payloads:
                    if _is_endpoint_on_cooldown(endpoint):
                        logger.debug("Embedding skip endpoint=%s reason=cooldown", endpoint)
                        continue

                    attempted_any = True
                    started = time.perf_counter()
                    try:
                        resp = await client.post(f"{settings.ollama_base_url}{endpoint}", json=payload)
                        resp.raise_for_status()
                        body = resp.json()

                        if isinstance(body, dict) and isinstance(body.get("embedding"), list):
                            emb = body["embedding"]
                        elif isinstance(body, dict) and isinstance(body.get("embeddings"), list) and body["embeddings"]:
                            emb = body["embeddings"][0]
                        else:
                            raise ValueError("Embedding response missing 'embedding(s)' field")

                        _mark_endpoint_healthy(endpoint)
                        elapsed_ms = (time.perf_counter() - started) * 1000
                        logger.info(
                            "Embedding succeeded endpoint=%s attempt=%d elapsed_ms=%.0f dim=%d",
                            endpoint, attempt, elapsed_ms, len(emb),
                        )
                        _record_embedding_success()
                        _put_cached_embedding(query_text, emb)
                        return emb
                    except httpx.TimeoutException as exc:
                        # Timeout means Ollama is loading the model (evicted by a running LLM),
                        # NOT that the endpoint is broken.  Do NOT put it on cooldown — that
                        # would block all subsequent requests for 45 s.
                        # Break immediately: trying the second endpoint is pointless since both
                        # hit the same Ollama process.
                        last_exc = exc
                        elapsed_ms = (time.perf_counter() - started) * 1000
                        logger.warning(
                            "Embedding timeout endpoint=%s attempt=%d elapsed_ms=%.0f — "
                            "Ollama likely loading model; retry with extended timeout",
                            endpoint, attempt, elapsed_ms,
                        )
                        timed_out = True
                        break  # don't try other endpoint, go to next attempt with slow timeout
                    except Exception as exc:
                        last_exc = exc
                        elapsed_ms = (time.perf_counter() - started) * 1000
                        logger.warning(
                            "Embedding attempt failed endpoint=%s attempt=%d elapsed_ms=%.0f error=%s (%s)",
                            endpoint, attempt, elapsed_ms, exc, type(exc).__name__,
                        )
                        if _is_non_retryable_embedding_error(exc):
                            logger.warning(
                                "Embedding endpoint=%s non-retryable status=%s",
                                endpoint, exc.response.status_code,
                            )
                            continue
                        # Real endpoint error (e.g. connection refused) — mark failed,
                        # try the other endpoint.
                        _mark_endpoint_failed(endpoint)

                # If both endpoints are in cooldown (no attempt made), force a direct
                # try using the slow timeout so the model can load.
                if not attempted_any:
                    endpoint = "/api/embeddings"
                    payload = {"model": settings.embedding_model, "prompt": query_text}
                    forced_timeout = _EMBED_TIMEOUT_SLOW
                    started = time.perf_counter()
                    try:
                        async with httpx.AsyncClient(timeout=forced_timeout) as forced_client:
                            resp = await forced_client.post(f"{settings.ollama_base_url}{endpoint}", json=payload)
                            resp.raise_for_status()
                            body = resp.json()
                            emb = body.get("embedding") or ((body.get("embeddings") or [None])[0])
                            if not isinstance(emb, list):
                                raise ValueError("Embedding response missing 'embedding(s)' field")
                            _mark_endpoint_healthy(endpoint)
                            elapsed_ms = (time.perf_counter() - started) * 1000
                            logger.info(
                                "Embedding succeeded endpoint=%s attempt=%d elapsed_ms=%.0f dim=%d (forced)",
                                endpoint, attempt, elapsed_ms, len(emb),
                            )
                            _record_embedding_success()
                            _put_cached_embedding(query_text, emb)
                            return emb
                    except Exception as exc:
                        last_exc = exc
                        elapsed_ms = (time.perf_counter() - started) * 1000
                        logger.warning(
                            "Embedding forced attempt failed endpoint=%s attempt=%d elapsed_ms=%.0f error=%s (%s)",
                            endpoint, attempt, elapsed_ms, exc, type(exc).__name__,
                        )
                        if not isinstance(exc, httpx.TimeoutException):
                            _mark_endpoint_failed(endpoint)

            if attempt < _EMBED_ATTEMPTS:
                await asyncio.sleep(_EMBED_BACKOFF_SECONDS * attempt)

    _record_embedding_failure()
    raise RuntimeError(f"Embedding failed after {_EMBED_ATTEMPTS} attempts: {last_exc}")


async def warmup_embedding() -> bool:
    """
    Best-effort embedding warm-up called once at startup.
    Uses a long timeout to survive cold model loading (Ollama loads from disk).
    Does NOT count failures towards the circuit breaker, so the first real
    user request is not penalised if warmup succeeds.
    After a successful warmup the model stays loaded in Ollama memory and
    subsequent calls complete in < 200 ms.
    """
    warmup_timeout = httpx.Timeout(connect=3.0, read=30.0, write=30.0, pool=3.0)
    test_text = "bank account balance transfer"

    endpoint_payloads = [
        ("/api/embeddings", {"model": settings.embedding_model, "prompt": test_text}),
        ("/api/embed", {"model": settings.embedding_model, "input": test_text}),
    ]

    logger.info(
        "Embedding warmup: pre-loading model '%s' on %s",
        settings.embedding_model,
        settings.ollama_base_url,
    )

    # Retry loop: at startup Ollama may return 500 because qwen/granite is still
    # loading.  We retry up to 3 times with a short pause so the warmup succeeds
    # once Ollama has finished initialising the other model.
    max_warmup_attempts = 3
    warmup_retry_delay = 4.0

    for warmup_attempt in range(1, max_warmup_attempts + 1):
        if warmup_attempt > 1:
            logger.info(
                "Embedding warmup retry %d/%d (waiting for Ollama to become ready)",
                warmup_attempt, max_warmup_attempts,
            )
            await asyncio.sleep(warmup_retry_delay)

        async with httpx.AsyncClient(timeout=warmup_timeout) as client:
            for endpoint, payload in endpoint_payloads:
                started = time.perf_counter()
                try:
                    resp = await client.post(f"{settings.ollama_base_url}{endpoint}", json=payload)
                    resp.raise_for_status()
                    body = resp.json()
                    if isinstance(body, dict) and isinstance(body.get("embedding"), list):
                        emb = body["embedding"]
                    elif isinstance(body, dict) and isinstance(body.get("embeddings"), list) and body["embeddings"]:
                        emb = body["embeddings"][0]
                    else:
                        raise ValueError("Embedding response missing expected field")
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    logger.info(
                        "Embedding warmup succeeded endpoint=%s attempt=%d elapsed_ms=%.0f dim=%d",
                        endpoint, warmup_attempt, elapsed_ms, len(emb),
                    )
                    _record_embedding_success()
                    _put_cached_embedding(test_text, emb)
                    return True
                except Exception as exc:
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    logger.warning(
                        "Embedding warmup failed endpoint=%s attempt=%d elapsed_ms=%.0f error=%s (%s)",
                        endpoint, warmup_attempt, elapsed_ms, exc, type(exc).__name__,
                    )

    logger.warning(
        "Embedding warmup: model '%s' unavailable after %d attempts — hybrid search will use "
        "sparse-only until the embedding service recovers",
        settings.embedding_model, max_warmup_attempts,
    )
    return False


@register_tool(
    name="search_banking_knowledge",
    description=(
        "Searches the bank's knowledge base for step-by-step guides, FAQs, and "
        "procedures. Use this for any banking question before answering from memory."
    ),
    schema=VectorSearchInput,
)
async def search_banking_knowledge(args: VectorSearchInput, memory=None) -> str:
    total_started = time.perf_counter()
    rows = []
    dense_hits = []
    sparse_hits = []

    # Step 1: Start sparse retrieval early; run in parallel with embedding/dense path.
    sparse_task = asyncio.create_task(_sparse_search_rows(args))

    # Step 2: Generate embedding
    embedding = None
    if embedding_backend_degraded():
        logger.info("Embedding backend degraded; continuing with sparse-only KB retrieval")
    else:
        try:
            embedding = await embed_query(args.query)
        except Exception as exc:
            logger.warning("Embedding failed: %s", exc)
            embedding = None

    # Step 3: Dimension guard
    if embedding is not None and len(embedding) != settings.embedding_dims:
        logger.error(
            "Embedding dim mismatch: got %d, expected %d", len(embedding), settings.embedding_dims
        )
        embedding = None

    # Step 4: Run dense retrieval if embedding is healthy
    if embedding is not None:
        try:
            dense_hits = await _dense_search_rows(args, embedding)
        except Exception as exc:
            logger.warning("Knowledge base dense retrieval failed: %s", exc)

    # Step 5: Sparse lexical retrieval for exact-term coverage (hybrid standard)
    try:
        sparse_hits = await sparse_task
    except Exception as exc:
        logger.warning("Knowledge base sparse retrieval failed: %s", exc)

    # Step 6: Reciprocal-rank fusion of dense + sparse candidates
    rows = _fuse_hybrid_results(dense_hits, sparse_hits, args.top_k * 3)
    rows = _rerank_fused_rows(args.query, rows, args.top_k)

    if not rows:
        payload = {
            "kind": "kb_search_result",
            "context_markdown": "No specific published knowledge-base articles matched this query.",
            "sources": [],
        }
        logger.info(
            "KB search total elapsed_ms=%.0f query=%r results=0",
            (time.perf_counter() - total_started) * 1000,
            args.query[:80],
        )
        return json.dumps(payload, ensure_ascii=False)

    out = []
    sources = []
    for row in rows:
        title = row.document_title or "Banking Article"
        content = (row.content_text or "").strip()
        chunk = f"**{title}**\n\n{content}"
        if row.image_urls:
            for url in row.image_urls:
                chunk += f"\n\n![Step screenshot]({url})"
        if row.source_url:
            chunk += f"\n\n[Learn more]({row.source_url})"
        out.append(chunk)

        render_blocks = row.render_blocks if isinstance(row.render_blocks, list) else []
        if not render_blocks and content:
            render_blocks = [{"type": "text", "content": content}]
            for url in (row.image_urls or []):
                render_blocks.append({"type": "image", "url": url, "alt": "Step screenshot"})

        sources.append({
            "id": str(row.id),
            "document_title": title,
            "source_url": row.source_url,
            "section_anchor": row.section_anchor,
            "chunk_index": row.chunk_index,
            "content_text": content,
            "image_urls": row.image_urls or [],
            "render_blocks": render_blocks,
        })

    result_count = len(out)
    header = f"Found {result_count} relevant article{'s' if result_count != 1 else ''} from the knowledge base:\n\n"
    logger.info("KB search total elapsed_ms=%.0f query=%r results=%d", (time.perf_counter() - total_started) * 1000, args.query[:80], result_count)
    context_markdown = header + "\n\n---\n\n".join(out)

    payload = {
        "kind": "kb_search_result",
        "context_markdown": context_markdown,
        "sources": sources,
    }
    return json.dumps(payload, ensure_ascii=False)
