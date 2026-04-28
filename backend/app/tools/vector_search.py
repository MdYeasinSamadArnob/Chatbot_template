# Tool: search_banking_knowledge — PgVector RAG for banking help
from sqlalchemy.future import select
import httpx
from app.config import settings
from app.tools.base import register_tool
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)


class VectorSearchInput(BaseModel):
    query: str = Field(..., description="User's banking question")
    top_k: int = Field(5, description="Number of results to return", ge=1, le=20)


async def embed_query(query_text: str) -> list[float]:
    """Embed a text string using the Ollama embedding endpoint."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.ollama_base_url}/api/embeddings",
            json={"model": settings.embedding_model, "prompt": query_text},
        )
        resp.raise_for_status()
        return resp.json()["embedding"]


@register_tool(
    name="search_banking_knowledge",
    description=(
        "Searches the bank's knowledge base for step-by-step guides, FAQs, and "
        "procedures. Use this for any banking question before answering from memory."
    ),
    schema=VectorSearchInput,
)
async def search_banking_knowledge(args: VectorSearchInput, memory=None) -> str:
    # Step 1: Generate embedding
    try:
        embedding = await embed_query(args.query)
    except Exception as exc:
        logger.warning("Embedding failed: %s", exc)
        return (
            "The knowledge base search is currently unavailable (embedding service error). "
            "Please answer the user's question using your general banking knowledge instead."
        )

    # Step 2: Query PostgreSQL via pgvector
    try:
        from app.db.connection import AsyncSessionLocal
        from app.db.models import BankingKnowledge

        async with AsyncSessionLocal() as session:
            stmt = (
                select(BankingKnowledge)
                .where(
                    BankingKnowledge.is_active == True,
                    BankingKnowledge.chunk_embedding.cosine_distance(embedding) < 0.40,
                )
                .order_by(BankingKnowledge.chunk_embedding.cosine_distance(embedding))
                .limit(args.top_k)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
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
            from app.db.models import BankingKnowledge
            from sqlalchemy import or_, func as sqlfunc

            async with AsyncSessionLocal() as session:
                words = [w for w in args.query.split() if len(w) > 2]
                fallback_stmt = (
                    select(BankingKnowledge)
                    .where(
                        BankingKnowledge.is_active == True,
                        or_(*(
                            BankingKnowledge.content_text.ilike(f"%{w}%")
                            for w in words[:5]
                        ))
                    )
                    .limit(args.top_k)
                )
                fb_result = await session.execute(fallback_stmt)
                rows = fb_result.scalars().all()
        except Exception:
            pass

    if not rows:
        return (
            "No specific articles found in the knowledge base for this query. "
            "Please answer using your general banking knowledge."
        )

    out = []
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
    result_count = len(out)
    header = f"Found {result_count} relevant article{'s' if result_count != 1 else ''} from the knowledge base:\n\n"
    return header + "\n\n---\n\n".join(out)
