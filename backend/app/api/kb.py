"""
Knowledge Base REST API.

Public endpoints (no auth):   GET /api/kb/documents, GET /api/kb/documents/{id},
                               GET /api/kb/categories, GET /api/kb/stats,
                               GET /api/kb/search (admin-only in prod — no secret needed for debug)

Admin endpoints (x-admin-secret header required):
    POST   /api/kb/documents
    PUT    /api/kb/documents/{id}
    DELETE /api/kb/documents/{id}
    PATCH  /api/kb/documents/{id}/publish
    POST   /api/kb/documents/{id}/content   (re-embed)
    POST   /api/kb/index
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

from app.config import settings
from app.db.connection import AsyncSessionLocal
from app.db.repositories import (
    kb_create_document,
    kb_delete_document,
    kb_get_document,
    kb_get_document_with_chunks,
    kb_get_stats,
    kb_insert_chunk,
    kb_list_categories,
    kb_list_documents,
    kb_replace_chunks,
    kb_set_embedding_status,
    kb_toggle_publish,
    kb_update_document,
)
from app.agent.kb_chunker import chunk_document
from app.tools.vector_search import embed_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kb", tags=["knowledge-base"])


# ── Auth dependency ────────────────────────────────────────────────────────

async def require_admin(x_admin_secret: str = Header(default="")) -> None:
    if not settings.admin_secret or x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Invalid or missing admin secret")


# ── Pydantic schemas ───────────────────────────────────────────────────────

class DocumentCreateRequest(BaseModel):
    title: str
    category: str
    subcategory: Optional[str] = None
    intent_tags: Optional[list[str]] = None
    author: Optional[str] = None
    is_published: bool = True
    content: str
    source_url: Optional[str] = None
    image_urls: Optional[list[str]] = None
    language: str = "en"


class DocumentUpdateRequest(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    intent_tags: Optional[list[str]] = None
    author: Optional[str] = None
    is_published: Optional[bool] = None


class ContentUpdateRequest(BaseModel):
    content: str
    source_url: Optional[str] = None
    image_urls: Optional[list[str]] = None
    language: str = "en"


# ── Background embedding task ──────────────────────────────────────────────

async def _embed_and_store(
    doc_id: str,
    doc_title: str,
    content: str,
    source_url: Optional[str],
    image_urls: Optional[list[str]],
    language: str,
    is_replace: bool,
) -> None:
    """
    Background task: chunk → embed → store.
    If is_replace=True uses INSERT-first/DELETE-old (zero downtime).
    Sets embedding_status to 'ready' on success or 'failed' on error.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await kb_set_embedding_status(session, doc_id, "processing")

    try:
        chunks = chunk_document(content, doc_title)

        if is_replace:
            chunks_data = []
            for c in chunks:
                embedding = await embed_query(c.text)
                chunks_data.append({
                    "document_title": doc_title,
                    "content_text": c.text,
                    "embedding": embedding,
                    "chunk_index": c.chunk_index,
                    "chunk_total": c.chunk_total,
                    "section_anchor": c.section_heading or None,
                    "image_urls": image_urls or [],
                    "source_url": source_url or "",
                    "language": language,
                    "document_type": "article",
                })
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    await kb_replace_chunks(session, doc_id, chunks_data)
        else:
            for c in chunks:
                embedding = await embed_query(c.text)
                async with AsyncSessionLocal() as session:
                    async with session.begin():
                        await kb_insert_chunk(
                            session,
                            doc_id=doc_id,
                            document_title=doc_title,
                            content_text=c.text,
                            embedding=embedding,
                            chunk_index=c.chunk_index,
                            chunk_total=c.chunk_total,
                            section_anchor=c.section_heading or None,
                            image_urls=image_urls or [],
                            source_url=source_url or "",
                            language=language,
                            document_type="article",
                        )

        async with AsyncSessionLocal() as session:
            async with session.begin():
                await kb_set_embedding_status(
                    session, doc_id, "ready",
                    embedded_at=datetime.now(timezone.utc),
                )
        logger.info("KB embed complete: doc_id=%s chunks=%d", doc_id, len(chunks))

    except Exception as exc:
        logger.error("KB embed failed: doc_id=%s error=%s", doc_id, exc)
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    await kb_set_embedding_status(session, doc_id, "failed")
        except Exception:
            pass


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/documents")
async def list_documents(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    published: Optional[bool] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        docs, total = await kb_list_documents(
            session,
            category=category,
            search_title=search,
            published_only=published or False,
            limit=limit,
            offset=offset,
        )
    return {"items": docs, "total": total, "limit": limit, "offset": offset}


@router.post("/documents", status_code=202, dependencies=[Depends(require_admin)])
async def create_document(body: DocumentCreateRequest) -> dict[str, Any]:
    chunks = chunk_document(body.content, body.title)
    estimated = len(chunks)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            doc_id = await kb_create_document(
                session,
                title=body.title,
                category=body.category,
                subcategory=body.subcategory,
                intent_tags=body.intent_tags,
                author=body.author,
                is_published=body.is_published,
            )

    asyncio.create_task(
        _embed_and_store(
            doc_id, body.title, body.content,
            body.source_url, body.image_urls, body.language,
            is_replace=False,
        )
    )
    return {"id": doc_id, "status": "embedding", "estimated_chunks": estimated}


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        result = await kb_get_document_with_chunks(session, doc_id)
    if not result:
        raise HTTPException(status_code=404, detail="Document not found")
    doc, chunks = result
    return {"document": doc, "chunks": chunks}


@router.put("/documents/{doc_id}", dependencies=[Depends(require_admin)])
async def update_document(doc_id: str, body: DocumentUpdateRequest) -> dict[str, Any]:
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    async with AsyncSessionLocal() as session:
        async with session.begin():
            updated = await kb_update_document(session, doc_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


@router.delete("/documents/{doc_id}", dependencies=[Depends(require_admin)])
async def delete_document(doc_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            deleted = await kb_delete_document(session, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


@router.patch("/documents/{doc_id}/publish", dependencies=[Depends(require_admin)])
async def toggle_publish(doc_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            new_state = await kb_toggle_publish(session, doc_id)
    if new_state is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"is_published": new_state}


@router.post("/documents/{doc_id}/content", status_code=202, dependencies=[Depends(require_admin)])
async def reembed_document(doc_id: str, body: ContentUpdateRequest) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        doc = await kb_get_document(session, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    chunks = chunk_document(body.content, doc["title"])
    estimated = len(chunks)

    asyncio.create_task(
        _embed_and_store(
            doc_id, doc["title"], body.content,
            body.source_url, body.image_urls, body.language,
            is_replace=True,
        )
    )
    return {"status": "embedding", "estimated_chunks": estimated}


@router.get("/search", dependencies=[Depends(require_admin)])
async def debug_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=20),
) -> dict[str, Any]:
    from app.tools.vector_search import search_banking_knowledge
    from app.tools.base import ToolInput

    class _Args:
        query = q
        top_k = limit

    result = await search_banking_knowledge(_Args())  # type: ignore[arg-type]
    return {"query": q, "result": result}


@router.get("/categories")
async def list_categories() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        cats = await kb_list_categories(session)
    return {"categories": cats}


@router.get("/stats")
async def get_stats() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        stats = await kb_get_stats(session)
    return stats


@router.post("/index", status_code=202, dependencies=[Depends(require_admin)])
async def build_index() -> dict[str, Any]:
    from sqlalchemy import text
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_hnsw_idx "
                "ON knowledge_chunks USING hnsw (chunk_embedding vector_cosine_ops) "
                "WITH (m = 16, ef_construction = 64)"
            ))
    return {"ok": True, "message": "HNSW index created or already exists"}
