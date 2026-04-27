"""
Socket.IO event handlers for the Bank Help Bot.

Events received from client:
    chat_message   — { message, conversation_id, profile? }
    reset_conversation — { conversation_id }

Events emitted to client:
    connected        — { conversation_id }
    history          — { messages: [{role, content}] }
    thinking_start   — {}
    thinking_end     — {}
    text_delta       — { delta: str }
    tool_call        — { toolCallId, toolName, args }
    tool_result      — { toolCallId, result }
    state            — { todos, notes, context }
    finish           — { finishReason, usage }
    error            — { message: str }
    conversation_reset — { conversation_id }
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import socketio

from app.agent.core import run_agent_loop_with_emitter
from app.agent.memory import clear_memory, get_or_create_memory
from app.agent.profiles import list_profiles
from app.config import settings

logger = logging.getLogger(__name__)

# ── Socket.IO server ───────────────────────────────────────────────────────

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.cors_origins + ["*"],  # mobile webview origins vary
    logger=False,
    engineio_logger=False,
)

# Map sid → conversation_id so we can persist on disconnect
_sid_to_conversation: dict[str, str] = {}


# ── Connection lifecycle ───────────────────────────────────────────────────

@sio.event
async def connect(sid: str, environ: dict, auth: dict | None = None) -> None:
    """
    Client connected. Accepts conversation_id from query params so
    the mobile app can resume a previous session.

    Query param: ?conversation_id=<uuid>
    """
    import urllib.parse

    query_string = environ.get("QUERY_STRING", "")
    params = dict(urllib.parse.parse_qsl(query_string))
    conversation_id = params.get("conversation_id", "")

    if not conversation_id:
        import uuid
        conversation_id = str(uuid.uuid4())

    _sid_to_conversation[sid] = conversation_id
    logger.info("Client %s connected (conversation=%s)", sid, conversation_id)

    # Restore memory from DB (non-blocking if DB is unavailable)
    memory = get_or_create_memory(conversation_id, settings.memory_persist_dir)
    await memory.load_from_db()

    # Acknowledge connection and send conversation ID
    await sio.emit("connected", {"conversation_id": conversation_id}, to=sid)

    # Send conversation history so the UI can replay previous messages
    history = [
        {"role": m["role"], "content": m.get("content", "")}
        for m in memory.get_messages()
        if m["role"] in ("user", "assistant")
    ]
    if history:
        await sio.emit("history", {"messages": history}, to=sid)


@sio.event
async def disconnect(sid: str) -> None:
    """
    Client disconnected. Persist memory to PostgreSQL.
    """
    conversation_id = _sid_to_conversation.pop(sid, None)
    if not conversation_id:
        return

    logger.info("Client %s disconnected (conversation=%s)", sid, conversation_id)
    memory = get_or_create_memory(conversation_id, settings.memory_persist_dir)
    # Fire-and-forget — don't block the disconnect handler
    asyncio.create_task(_persist(memory))


async def _persist(memory) -> None:
    try:
        await memory.save_to_db()
    except Exception as exc:
        logger.warning("Background persist failed: %s", exc)


# ── Chat message handler ───────────────────────────────────────────────────

@sio.event
async def chat_message(sid: str, data: dict[str, Any]) -> None:
    """
    Receive a message from the client and run the agent loop.

    Expected payload:
        { message: str, conversation_id: str, profile?: str }
    """
    conversation_id = data.get("conversation_id") or _sid_to_conversation.get(sid, "")
    raw_message = str(data.get("message", "")).strip()
    profile_name = data.get("profile", "banking")

    if not raw_message:
        await sio.emit("error", {"message": "Empty message."}, to=sid)
        return

    if not conversation_id:
        await sio.emit("error", {"message": "No conversation_id provided."}, to=sid)
        return

    # Update sid→conversation mapping in case it changed
    _sid_to_conversation[sid] = conversation_id

    memory = get_or_create_memory(conversation_id, settings.memory_persist_dir)

    # Bind emit_fn to this specific client
    async def emit_fn(event: str, payload: Any) -> None:
        await sio.emit(event, payload, to=sid)

    try:
        await run_agent_loop_with_emitter(
            message=raw_message,
            conversation_id=conversation_id,
            memory=memory,
            emit_fn=emit_fn,
            profile_name=profile_name,
            context=data.get("context"),
            session_state=data.get("session_state"),
        )
    except Exception as exc:
        logger.exception("Unhandled error in agent loop for %s", conversation_id)
        await sio.emit("error", {"message": f"Internal server error: {exc}"}, to=sid)


# ── Reset conversation ─────────────────────────────────────────────────────

@sio.event
async def reset_conversation(sid: str, data: dict[str, Any]) -> None:
    """
    Clear in-memory state and remove persisted messages from DB.
    """
    conversation_id = data.get("conversation_id") or _sid_to_conversation.get(sid, "")
    if not conversation_id:
        return

    clear_memory(conversation_id)

    # Delete DB records
    try:
        from app.db.connection import AsyncSessionLocal
        from app.db.repositories import save_messages
        async with AsyncSessionLocal() as session:
            await save_messages(session, conversation_id, [])
    except Exception as exc:
        logger.warning("DB clear failed for %s: %s", conversation_id, exc)

    logger.info("Conversation reset for %s (sid=%s)", conversation_id, sid)
    await sio.emit("conversation_reset", {"conversation_id": conversation_id}, to=sid)
