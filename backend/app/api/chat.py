"""
Chat API endpoints.

POST /api/agent/chat-streaming  — main streaming chat
GET  /api/agent/profiles        — list available profiles
GET  /api/agent/health          — liveness check
DELETE /api/agent/conversation/{id} — reset a conversation
"""

from __future__ import annotations

import uuid
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.core import run_agent_loop
from app.agent.memory import clear_memory, get_or_create_memory, list_conversations
from app.agent.profiles import list_profiles
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


# ── Request / Response schemas ─────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8192)
    conversation_id: str | None = Field(
        default=None,
        description="Reuse an existing conversation. Omit to start a new one.",
    )
    profile: str = Field(default="default", description="Agent profile name")
    context: dict | None = Field(
        default=None,
        description="Optional context dict (capabilities, user info, etc.)",
    )
    session_state: dict | None = Field(
        default=None,
        description="Session state from the previous response (todos, notes, etc.)",
    )


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/chat-streaming")
async def chat_streaming(req: ChatRequest) -> StreamingResponse:
    """
    Main streaming chat endpoint.

    Returns a Server-Sent Events stream in the AI SDK v4 line protocol:
      0:"text"           — text delta
      9:{tool_call}      — tool invocation
      a:{tool_result}    — tool result
      2:[{type, data}]   — structured data (state updates, etc.)
      3:"error"          — error
      d:{finish, usage}  — stream finished

    The X-Conversation-Id response header contains the conversation ID
    (useful when the client omits conversation_id in the request).
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
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
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
