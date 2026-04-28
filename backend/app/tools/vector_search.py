# Tool: search_banking_knowledge — PgVector RAG for banking help
import asyncio
import logging
import time

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.future import select

from app.config import settings
from app.tools.base import register_tool

logger = logging.getLogger(__name__)

# Keep embedding calls fast and resilient under Ollama instability.
_EMBED_ATTEMPTS = 2
_EMBED_BACKOFF_SECONDS = 0.35
_EMBED_TIMEOUT = httpx.Timeout(connect=2.0, read=6.0, write=6.0, pool=2.0)
_ENDPOINT_COOLDOWN_SECONDS = 45.0
_ENDPOINT_FAILURE_UNTIL: dict[str, float] = {}
_EMBED_SEMAPHORE = asyncio.Semaphore(1)


def _is_endpoint_on_cooldown(endpoint: str) -> bool:
    return _ENDPOINT_FAILURE_UNTIL.get(endpoint, 0.0) > time.monotonic()


def _mark_endpoint_failed(endpoint: str) -> None:
    _ENDPOINT_FAILURE_UNTIL[endpoint] = time.monotonic() + _ENDPOINT_COOLDOWN_SECONDS


def _mark_endpoint_healthy(endpoint: str) -> None:
    _ENDPOINT_FAILURE_UNTIL.pop(endpoint, None)


class VectorSearchInput(BaseModel):
    query: str = Field(..., description="User's banking question")
    top_k: int = Field(5, description="Number of results to return", ge=1, le=20)


async def embed_query(query_text: str) -> list[float]:
    """Embed a text string with retry and endpoint fallback for Ollama."""
    last_exc: Exception | None = None

    async with _EMBED_SEMAPHORE:
        async with httpx.AsyncClient(timeout=_EMBED_TIMEOUT) as client:
            for attempt in range(1, _EMBED_ATTEMPTS + 1):
                # Prefer the endpoint that has proven stable in this environment.
                endpoint_payloads = [
                    ("/api/embeddings", {"model": settings.embedding_model, "prompt": query_text}),
                    ("/api/embed", {"model": settings.embedding_model, "input": query_text}),
                ]

                attempted_any = False
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
                            endpoint,
                            attempt,
                            elapsed_ms,
                            len(emb),
                        )
                        return emb
                    except Exception as exc:
                        last_exc = exc
                        _mark_endpoint_failed(endpoint)
                        elapsed_ms = (time.perf_counter() - started) * 1000
                        logger.warning(
                            "Embedding attempt failed endpoint=%s attempt=%d elapsed_ms=%.0f error=%s",
                            endpoint,
                            attempt,
                            elapsed_ms,
                            exc,
                        )

                # If both endpoints are in cooldown, force one direct try on primary endpoint.
                if not attempted_any:
                    endpoint = "/api/embeddings"
                    payload = {"model": settings.embedding_model, "prompt": query_text}
                    started = time.perf_counter()
                    try:
                        resp = await client.post(f"{settings.ollama_base_url}{endpoint}", json=payload)
                        resp.raise_for_status()
                        body = resp.json()
                        emb = body.get("embedding") or ((body.get("embeddings") or [None])[0])
                        if not isinstance(emb, list):
                            raise ValueError("Embedding response missing 'embedding(s)' field")
                        _mark_endpoint_healthy(endpoint)
                        elapsed_ms = (time.perf_counter() - started) * 1000
                        logger.info(
                            "Embedding succeeded endpoint=%s attempt=%d elapsed_ms=%.0f dim=%d (forced)",
                            endpoint,
                            attempt,
                            elapsed_ms,
                            len(emb),
                        )
                        return emb
                    except Exception as exc:
                        last_exc = exc
                        _mark_endpoint_failed(endpoint)
                        elapsed_ms = (time.perf_counter() - started) * 1000
                        logger.warning(
                            "Embedding forced attempt failed endpoint=%s attempt=%d elapsed_ms=%.0f error=%s",
                            endpoint,
                            attempt,
                            elapsed_ms,
                            exc,
                        )

                if attempt < _EMBED_ATTEMPTS:
                    await asyncio.sleep(_EMBED_BACKOFF_SECONDS * attempt)

    raise RuntimeError(f"Embedding failed after {_EMBED_ATTEMPTS} attempts: {last_exc}")


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
    # Step 1: Generate embedding
    try:
        embedding = await embed_query(args.query)
    except Exception as exc:
        logger.warning("Embedding failed: %s", exc)
        return (
            "The knowledge base search is currently unavailable (embedding service error). "
            "Please answer the user's question using your general banking knowledge instead."
        )

    # Step 2: Dimension guard
    if len(embedding) != settings.embedding_dims:
        logger.error(
            "Embedding dim mismatch: got %d, expected %d", len(embedding), settings.embedding_dims
        )
        return (
            "Knowledge base search unavailable — embedding dimension mismatch. "
            "Please answer the user's question using your general banking knowledge instead."
        )

    # Step 3: Query PostgreSQL via pgvector (join knowledge_documents for is_published filter)
    try:
        from app.db.connection import AsyncSessionLocal
        from app.db.models import BankingKnowledge, KnowledgeDocument

        vec_started = time.perf_counter()
        async with AsyncSessionLocal() as session:
            # Tune HNSW recall for this session
            await session.execute(text("SET LOCAL hnsw.ef_search = 40"))
            stmt = (
                select(BankingKnowledge)
                .join(KnowledgeDocument, BankingKnowledge.document_id == KnowledgeDocument.id)
                .where(
                    KnowledgeDocument.is_published == True,
                    BankingKnowledge.is_active == True,
                    BankingKnowledge.chunk_embedding.isnot(None),
                    BankingKnowledge.chunk_embedding.cosine_distance(embedding) < 0.40,
                )
                .order_by(BankingKnowledge.chunk_embedding.cosine_distance(embedding))
                .limit(args.top_k)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
        logger.info("KB vector query elapsed_ms=%.0f rows=%d", (time.perf_counter() - vec_started) * 1000, len(rows))
    except Exception as exc:
        logger.warning("Knowledge base DB query failed: %s", exc)
        return (
            "The knowledge base search is currently unavailable (database not ready). "
            "Please answer the user's question using your general banking knowledge instead."
        )

    if not rows:
        # Fallback: keyword search when no vector matches found
        try:
            from app.db.connection import AsyncSessionLocal
            from app.db.models import BankingKnowledge, KnowledgeDocument
            from sqlalchemy import or_

            fb_started = time.perf_counter()
            async with AsyncSessionLocal() as session:
                words = [w for w in args.query.split() if len(w) > 2]
                fallback_stmt = (
                    select(BankingKnowledge)
                    .join(KnowledgeDocument, BankingKnowledge.document_id == KnowledgeDocument.id)
                    .where(
                        KnowledgeDocument.is_published == True,
                        BankingKnowledge.is_active == True,
                        BankingKnowledge.chunk_embedding.isnot(None),
                        or_(*(
                            BankingKnowledge.content_text.ilike(f"%{w}%")
                            for w in words[:5]
                        ))
                    )
                    .limit(args.top_k)
                )
                fb_result = await session.execute(fallback_stmt)
                rows = fb_result.scalars().all()
            logger.info("KB keyword fallback elapsed_ms=%.0f rows=%d", (time.perf_counter() - fb_started) * 1000, len(rows))
        except Exception:
            pass

    if not rows:
        return (
            "No specific articles found in the knowledge base for this query. "
            "Please answer using your general banking knowledge."
        )

    out = []
    for row in rows:
        if row.chunk_embedding is None:
            continue
        title = row.document_title or "Banking Article"
        content = (row.content_text or "").strip()
        chunk = f"**{title}**\n\n{content}"
        if row.image_urls:
            for url in row.image_urls:
                chunk += f"\n\n![Step screenshot]({url})"
        if row.source_url:
            chunk += f"\n\n[Learn more]({row.source_url})"
        out.append(chunk)
    result_count = len(out)
    header = f"Found {result_count} relevant article{'s' if result_count != 1 else ''} from the knowledge base:\n\n"
    logger.info("KB search total elapsed_ms=%.0f query=%r results=%d", (time.perf_counter() - total_started) * 1000, args.query[:80], result_count)
    return header + "\n\n---\n\n".join(out)
