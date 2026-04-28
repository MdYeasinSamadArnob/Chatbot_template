"""
Chat API endpoints.

POST /api/agent/chat-streaming      — main streaming chat
GET  /api/agent/profiles            — list available profiles
GET  /api/agent/health              — liveness check
DELETE /api/agent/conversation/{id} — reset a conversation
POST /api/agent/knowledge           — ingest FAQ / article into knowledge base
GET  /api/agent/escalations         — list escalation tickets (admin)
"""

from __future__ import annotations

import uuid
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List

from app.agent.core import run_agent_loop
from app.agent.memory import clear_memory, get_or_create_memory, list_conversations
from app.agent.profiles import list_profiles
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


# ── Request / Response schemas ─────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: str | None = Field(
        default=None,
        description="Reuse an existing conversation. Omit to start a new one.",
    )
    profile: str = Field(default="banking", description="Agent profile name")
    context: dict | None = Field(
        default=None,
        description="Optional context dict (capabilities, user info, etc.)",
    )
    session_state: dict | None = Field(
        default=None,
        description="Session state from the previous response (todos, notes, etc.)",
    )


class KnowledgeIngestRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    content: str = Field(..., min_length=1)
    source_url: Optional[str] = Field(default=None)
    image_urls: Optional[List[str]] = Field(default=None)


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/chat-streaming")
async def chat_streaming(req: ChatRequest) -> StreamingResponse:
    """
    Main streaming chat endpoint (SSE fallback, Socket.IO is primary).
    """
    conversation_id = req.conversation_id or str(uuid.uuid4())
    memory = get_or_create_memory(conversation_id, settings.memory_persist_dir)

    async def generate():
        try:
            async for chunk in run_agent_loop(
                message=req.message,
                conversation_id=conversation_id,
                memory=memory,
                profile_name=req.profile,
                context=req.context,
                session_state=req.session_state,
            ):
                yield chunk
        except Exception as exc:
            logger.exception("Unhandled error in agent loop for %s", conversation_id)
            from app.agent.streaming import error_part
            yield error_part(f"Internal server error: {exc}")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "X-Conversation-Id": conversation_id,
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/profiles")
async def get_profiles() -> dict:
    """List all registered agent profiles."""
    return {"profiles": list_profiles()}


@router.get("/health")
async def health() -> dict:
    """Liveness probe."""
    return {
        "status": "ok",
        "model": settings.model_name,
        "active_conversations": len(list_conversations()),
    }


@router.delete("/conversation/{conversation_id}")
async def reset_conversation(conversation_id: str) -> dict:
    """Clear conversation history and session state."""
    clear_memory(conversation_id)
    return {"status": "ok", "conversation_id": conversation_id}


@router.post("/knowledge")
async def ingest_knowledge(req: KnowledgeIngestRequest) -> dict:
    """
    Ingest a FAQ article into the knowledge base.

    Embeds the content via Ollama and stores it in the BankingKnowledge table.
    """
    try:
        from app.tools.vector_search import embed_query
        embedding = await embed_query(req.content)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Embedding service unavailable: {exc}")

    try:
        from app.db.connection import AsyncSessionLocal
        from app.db.repositories import upsert_knowledge_chunk
        async with AsyncSessionLocal() as session:
            row_id = await upsert_knowledge_chunk(
                session=session,
                title=req.title,
                content=req.content,
                embedding=embedding,
                image_urls=req.image_urls or [],
                source_url=req.source_url or "",
            )
    except Exception as exc:
        logger.exception("Knowledge ingest DB error")
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")

    return {"status": "ok", "id": row_id, "title": req.title}


@router.get("/escalations")
async def list_escalations(
    status: Optional[str] = Query(default=None, description="Filter by status: 'open' | 'resolved'"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """
    List escalation tickets. Intended for admin / support team dashboards.
    """
    try:
        from app.db.connection import AsyncSessionLocal
        from app.db.repositories import list_escalation_tickets
        async with AsyncSessionLocal() as session:
            tickets = await list_escalation_tickets(session, status=status, limit=limit)
    except Exception as exc:
        logger.exception("Failed to list escalations")
        raise HTTPException(status_code=500, detail=str(exc))

    return {"tickets": tickets, "count": len(tickets)}

