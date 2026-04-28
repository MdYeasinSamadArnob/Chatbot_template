"""
Socket.IO event handlers for the Bank Help Bot.

Events received from client:
    chat_message          — { message, conversation_id, profile? }
    reset_conversation    — { conversation_id }

Events emitted to client:
    connected             — { conversation_id }
    history               — { messages: [{role, content}] }
    thinking_start        — {}
    thinking_end          — {}
    text_delta            — { delta: str }
    tool_call             — { toolCallId, toolName, args }
    tool_result           — { toolCallId, result }
    state                 — { todos, notes, context, suggested_actions?, ... }
    finish                — { finishReason, usage, suggestedActions }
    chips_update          — { suggestedActions: [{label, value}] }
    error                 — { message: str }
    conversation_reset    — { conversation_id }

Routing decision tree (executed before every agent loop call):
  1. Active flow?         → FlowEngine.advance()
  2. Clarification?       → run_reexplain_loop_with_emitter()
  3. Classify intent      → route to flow or normal agent loop
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import socketio

from app.agent.core import run_agent_loop_with_emitter, run_reexplain_loop_with_emitter
from app.agent.memory import clear_memory, get_or_create_memory
from app.agent.profiles import list_profiles
from app.config import settings

logger = logging.getLogger(__name__)

# ── Socket.IO server ───────────────────────────────────────────────────────

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.cors_origins + ["*"],
    logger=False,
    engineio_logger=False,
)

# Map sid → conversation_id so we can persist on disconnect
_sid_to_conversation: dict[str, str] = {}

# Per-conversation locks to prevent concurrent agent loop execution
_conversation_locks: dict[str, asyncio.Lock] = {}

# Simple PII patterns to redact from logs (not from LLM input — user chose to share)
_PII_LOG_RE = re.compile(r"\b\d{13,19}\b|\b\d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b")

# Detects yes/no question tails in streamed answers for chip generation
_YN_QUESTION_RE = re.compile(
    r"\b(would you like|do you (want|need)|shall i|is there anything (else|more)|"
    r"can i (help|assist)|need (more|further)|want to know more|would you also)\b",
    re.IGNORECASE,
)


def _redact_pii(text: str) -> str:
    """Replace card/account numbers in log strings with ***."""
    return _PII_LOG_RE.sub("***", text)


def _get_lock(conversation_id: str) -> asyncio.Lock:
    if conversation_id not in _conversation_locks:
        _conversation_locks[conversation_id] = asyncio.Lock()
    return _conversation_locks[conversation_id]


def _get_last_bot_message(memory) -> str:
    """Return the most recent assistant message content, or empty string."""
    for msg in reversed(memory.get_messages()):
        if msg.get("role") == "assistant" and msg.get("content"):
            return msg["content"]
    return ""


# ── Connection lifecycle ───────────────────────────────────────────────────

@sio.event
async def connect(sid: str, environ: dict, auth: dict | None = None) -> None:
    import urllib.parse
    import uuid as uuid_module

    query_string = environ.get("QUERY_STRING", "")
    params = dict(urllib.parse.parse_qsl(query_string))
    conversation_id = params.get("conversation_id", "")

    if not conversation_id:
        conversation_id = str(uuid_module.uuid4())

    _sid_to_conversation[sid] = conversation_id
    logger.info("Client %s connected (conversation=%s)", sid, conversation_id)

    memory = get_or_create_memory(conversation_id, settings.memory_persist_dir)
    await memory.load_from_db()

    # Expire stale flows on reconnect
    state = memory.get_state()
    flow_data = state.get("_flow")
    if flow_data:
        from app.agent.flow_engine import FLOW_MAX_AGE_MINUTES
        from datetime import datetime, timezone
        started = flow_data.get("started_at", "")
        if started:
            try:
                age = (datetime.now(tz=timezone.utc) - datetime.fromisoformat(started)).total_seconds() / 60
                if age > FLOW_MAX_AGE_MINUTES:
                    state.pop("_flow", None)
                    memory.update_state(state)
            except (ValueError, TypeError):
                pass

    await sio.emit("connected", {"conversation_id": conversation_id}, to=sid)

    history = [
        {"role": m["role"], "content": m.get("content", "")}
        for m in memory.get_messages()
        if m["role"] in ("user", "assistant")
    ]
    if history:
        await sio.emit("history", {"messages": history}, to=sid)


@sio.event
async def disconnect(sid: str) -> None:
    conversation_id = _sid_to_conversation.pop(sid, None)
    if not conversation_id:
        return
    logger.info("Client %s disconnected (conversation=%s)", sid, conversation_id)
    memory = get_or_create_memory(conversation_id, settings.memory_persist_dir)
    asyncio.create_task(_persist(memory))
    # Clean up lock when no longer needed
    _conversation_locks.pop(conversation_id, None)


async def _persist(memory) -> None:
    try:
        await memory.save_to_db()
    except Exception as exc:
        logger.warning("Background persist failed: %s", exc)


# ── Chat message handler ───────────────────────────────────────────────────

@sio.event
async def chat_message(sid: str, data: dict[str, Any]) -> None:
    """
    Main entry point. Runs the full routing decision tree before
    delegating to the appropriate handler.
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

    logger.info("chat_message sid=%s conv=%s msg=%r", sid, conversation_id, _redact_pii(raw_message[:120]))

    # Prevent concurrent loops for the same conversation
    lock = _get_lock(conversation_id)
    if lock.locked():
        await sio.emit("error", {"message": "Please wait for the previous response to complete."}, to=sid)
        return

    _sid_to_conversation[sid] = conversation_id
    memory = get_or_create_memory(conversation_id, settings.memory_persist_dir)

    async def emit_fn(event: str, payload: Any) -> None:
        await sio.emit(event, payload, to=sid)

    async with lock:
        try:
            await _route_message(
                raw_message=raw_message,
                conversation_id=conversation_id,
                memory=memory,
                emit_fn=emit_fn,
                profile_name=profile_name,
                extra_context=data.get("context"),
                session_state=data.get("session_state"),
            )
        except Exception as exc:
            logger.exception("Unhandled error routing message for %s", conversation_id)
            await sio.emit("error", {"message": f"Internal server error: {exc}"}, to=sid)


# ── KB pre-fetch helper ────────────────────────────────────────────────────

async def _prefetch_kb(query: str) -> tuple[str, float]:
    """
    Pre-fetch knowledge base context in parallel with intent classification.
    Returns (context_text, confidence_score).
    Confidence: 0.8 = strong (2+ results), 0.55 = partial (1 result),
                0.4 = keyword fallback, 0.0 = no match / error.
    """
    try:
        from app.tools.vector_search import search_banking_knowledge, VectorSearchInput
        result = await search_banking_knowledge(VectorSearchInput(query=query, top_k=3))
        if not result or "unavailable" in result.lower() or "No specific articles" in result:
            return "", 0.0
        # Estimate confidence from KB response content
        match = re.search(r"Found (\d+) relevant", result)
        if match:
            n = int(match.group(1))
            confidence = 0.8 if n >= 2 else 0.55
        else:
            # Keyword-fallback response (no "Found N" header) — lower confidence
            confidence = 0.4
        logger.debug("[KB prefetch] confidence=%.2f result_len=%d", confidence, len(result))
        return result, confidence
    except Exception as exc:
        logger.warning("KB prefetch failed: %s", exc)
        return "", 0.0


# ── Chip builder helper ────────────────────────────────────────────────────

def _build_chips(classification, answer_tail: str = "") -> list[dict]:
    """
    Build quick-reply chips from:
      1. Yes/No detection on last 200 chars of answer
      2. next_likely intent chips (LLM-predicted follow-ups)
      3. Current intent's suggested_actions
    Deduplicates by 'value', caps at 6.
    """
    from app.agent.intent_taxonomy import INTENTS
    chips: list[dict] = []
    seen: set[str] = set()

    def _add(chip: dict) -> None:
        v = str(chip.get("value", ""))
        if v and v not in seen:
            seen.add(v)
            chips.append(chip)

    # 1. Yes/No chips when answer tail ends with a relevant question
    tail = answer_tail.strip()[-200:] if answer_tail else ""
    if tail.endswith("?") and _YN_QUESTION_RE.search(tail):
        _add({"label": "Yes, please", "value": "Yes, please"})
        _add({"label": "No, that's all", "value": "No, that's all I need"})

    # 2. Predictive chips from next_likely (LLM-generated per-message)
    for intent_name in (getattr(classification, "next_likely", None) or [])[:2]:
        intent_def = INTENTS.get(intent_name)
        if intent_def and intent_def.suggested_actions:
            _add(intent_def.suggested_actions[0])

    # 3. Current intent chips
    for chip in (classification.suggested_actions or []):
        _add(chip)
        if len(chips) >= 6:
            break

    return chips[:6]


async def _route_message(
    raw_message: str,
    conversation_id: str,
    memory,
    emit_fn,
    profile_name: str,
    extra_context: dict | None,
    session_state: dict | None,
) -> None:
    """
    Routing decision tree. Mutates memory.session_state in-place.

    Performance path:
      1. Active flow check (sync, <1ms) — handles own thinking_start
      2. Emit thinking_start IMMEDIATELY (<100ms) — visible feedback before LLM
      3. Fire classify_task + kb_task in parallel
      4. Await classify_task; kb_task completes concurrently
      5. Clarification / flow-activation routing
      6. Inject KB into context with confidence gating
      7. Run agent loop (no extra tool-decision call when KB is strong)
      8. Emit finish with final chips
    """
    from app.agent.intent_classifier import (
        classify_intent,
        detect_clarification,
        detect_abort,
        detect_negative_sentiment,
    )
    from app.agent.flow_engine import FlowEngine

    # ── Seed session state from client (cross-request continuity) ─────
    if session_state:
        memory.update_state(session_state)

    current_state = memory.get_state()

    # ── Track negative sentiment (sync, fast) ─────────────────────────
    if detect_negative_sentiment(raw_message):
        neg_count = int(current_state.get("_negative_sentiment_count", 0)) + 1
        current_state["_negative_sentiment_count"] = neg_count
        memory.update_state(current_state)

    # ── 1. Active flow? (sync, no LLM needed) ────────────────────────
    # Must run BEFORE thinking_start — flow handler manages its own thinking lifecycle.
    engine = FlowEngine.from_session(current_state)
    if engine:
        await _handle_flow(
            raw_message=raw_message,
            memory=memory,
            emit_fn=emit_fn,
            engine=engine,
            profile_name=profile_name,
            extra_context=extra_context,
            conversation_id=conversation_id,
        )
        return

    # ── INSTANT: emit thinking_start <100ms ──────────────────────────
    # Fires before any LLM calls so user sees feedback immediately.
    await emit_fn("thinking_start", {})

    # ── 2. Fire parallel tasks ────────────────────────────────────────
    route_started = time.perf_counter()
    is_first = len([m for m in memory.get_messages() if m.get("role") == "user"]) == 0
    classify_task: asyncio.Task = asyncio.create_task(
        classify_intent(
            message=raw_message,
            conversation_history=memory.get_messages(),
            is_first_message=is_first,
        )
    )
    kb_task: asyncio.Task = asyncio.create_task(_prefetch_kb(raw_message))

    # ── 3. Await classification (kb_task runs concurrently) ───────────
    classify_wait_started = time.perf_counter()
    try:
        classification = await classify_task
    except Exception as exc:
        logger.warning("Intent classification failed: %s — defaulting to general_faq", exc)
        kb_task.cancel()
        from app.agent.intent_classifier import ClassificationResult
        from app.agent.intent_taxonomy import FALLBACK_INTENT
        intent_def = FALLBACK_INTENT
        classification = ClassificationResult(
            intent="general_faq", confidence=0.4,
            is_clarification=False, is_abort=False, is_negative_sentiment=False,
            suggested_profile=intent_def.profile, flow_name=None,
            required_slots=[], suggested_actions=intent_def.suggested_actions,
        )
    classify_wait_ms = (time.perf_counter() - classify_wait_started) * 1000
    logger.info(
        "[%s] classify_intent wait=%.0f ms intent=%s confidence=%.2f",
        conversation_id,
        classify_wait_ms,
        classification.intent,
        classification.confidence,
    )

    # ── 4. Clarification request? ─────────────────────────────────────
    last_bot = _get_last_bot_message(memory)
    if last_bot and detect_clarification(raw_message, last_bot):
        kb_task.cancel()
        clarif_count = int(current_state.get("_clarification_count", 0)) + 1
        current_state["_clarification_count"] = clarif_count
        memory.update_state(current_state)

        await run_reexplain_loop_with_emitter(
            user_message=raw_message,
            last_bot_response=last_bot,
            conversation_id=conversation_id,
            memory=memory,
            emit_fn=emit_fn,
            suggested_actions=classification.suggested_actions,
            skip_initial_thinking=True,  # already emitted at top
        )

        # After 2nd clarification, offer human escalation
        if clarif_count >= 2:
            updated = memory.get_state()
            updated["suggested_actions"] = [
                {"label": "Connect me to an agent", "value": "I want to speak to a support agent"},
            ]
            memory.update_state(updated)
            await emit_fn("state", memory.get_state())
        return

    # ── 5. Store topic + check for flow activation ────────────────────
    current_state["_last_topic"] = classification.intent
    memory.update_state(current_state)

    if classification.flow_name and classification.confidence >= 0.65:
        kb_task.cancel()
        new_engine = FlowEngine.activate(classification.flow_name, current_state)
        memory.update_state(current_state)

        if new_engine:
            intro_text, first_quick_replies = new_engine.get_intro()
            memory.add_user_message(raw_message)
            # thinking_start already emitted — just end it, then emit text
            await emit_fn("thinking_end", {})
            await emit_fn("text_delta", {"delta": intro_text})
            state_update = memory.get_state()
            state_update.pop("suggested_actions", None)
            memory.update_state(state_update)
            await emit_fn("state", {k: v for k, v in memory.get_state().items() if k != "suggested_actions"})
            await emit_fn("finish", {"finishReason": "stop", "usage": {"promptTokens": 0, "completionTokens": 0}, "suggestedActions": first_quick_replies or []})
            memory.add_assistant_message(content=intro_text)
            return

    # ── 6. Await KB result (likely already done by now) ───────────────
    kb_wait_started = time.perf_counter()
    try:
        kb_context, kb_confidence = await asyncio.wait_for(kb_task, timeout=8.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        kb_context, kb_confidence = "", 0.0
        logger.warning("[%s] KB prefetch timed out — LLM will use tools if needed", conversation_id)
    kb_wait_ms = (time.perf_counter() - kb_wait_started) * 1000
    logger.info(
        "[%s] kb_prefetch wait=%.0f ms confidence=%.2f context_len=%d",
        conversation_id,
        kb_wait_ms,
        kb_confidence,
        len(kb_context),
    )

    logger.debug("[%s] KB confidence=%.2f context_len=%d", conversation_id, kb_confidence, len(kb_context))

    # ── 7. Fire chip-pusher task (emits chips_update mid-stream) ─────
    async def _push_chips_bg() -> list[dict]:
        chips = _build_chips(classification)
        await emit_fn("chips_update", {"suggestedActions": chips})
        return chips

    chip_task: asyncio.Task = asyncio.create_task(_push_chips_bg())

    # ── 8. Build enriched context ──────────────────────────────────────
    enriched_context = dict(extra_context or {})
    enriched_context.update({
        "_last_topic": current_state.get("_last_topic", ""),
        "_negative_sentiment_count": current_state.get("_negative_sentiment_count", 0),
        "_clarification_count": current_state.get("_clarification_count", 0),
        "_kb_context": kb_context,
        "_kb_confidence": kb_confidence,
    })

    # Surface greeting quick-replies for first message
    if is_first or classification.intent == "greeting":
        current_state["suggested_actions"] = classification.suggested_actions
        memory.update_state(current_state)

    # ── 9. Run full agent loop (tools intact, KB pre-injected if confident) ──
    usage = await run_agent_loop_with_emitter(
        message=raw_message,
        conversation_id=conversation_id,
        memory=memory,
        emit_fn=emit_fn,
        profile_name=profile_name,
        context=enriched_context,
        session_state=None,  # already seeded above
        suggested_actions=classification.suggested_actions or [],
        skip_initial_thinking=True,  # already emitted at step 2
    )
    agent_loop_ms = (time.perf_counter() - route_started) * 1000 - classify_wait_ms - kb_wait_ms
    logger.info(
        "[%s] agent_loop approx=%.0f ms total_route=%.0f ms",
        conversation_id,
        max(agent_loop_ms, 0.0),
        (time.perf_counter() - route_started) * 1000,
    )

    # ── 10. Bulletproof chip timing ───────────────────────────────────
    # Guarantee chips always appear even if classification resolved very late.
    if not chip_task.done():
        try:
            await asyncio.wait_for(asyncio.shield(chip_task), timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            logger.warning("[%s] Chip task did not complete in time", conversation_id)

    # Build final chips using answer tail for yes/no detection
    last_answer = _get_last_bot_message(memory) or ""
    final_chips = _build_chips(classification, answer_tail=last_answer[-200:])

    # ── 11. Emit finish with merged chips ─────────────────────────────
    await emit_fn("finish", {
        "finishReason": "stop",
        "usage": {
            "promptTokens": usage.get("promptTokens", 0),
            "completionTokens": usage.get("completionTokens", 0),
        },
        "suggestedActions": final_chips,
    })


async def _handle_flow(
    raw_message: str,
    memory,
    emit_fn,
    engine,
    profile_name: str,
    extra_context: dict | None,
    conversation_id: str,
) -> None:
    """Process a message against an active flow."""
    current_state = memory.get_state()
    result = engine.advance(
        user_input=raw_message,
        session_state=current_state,
        bank_name=settings.bank_name,
    )
    memory.update_state(current_state)

    memory.add_user_message(raw_message)

    await emit_fn("thinking_start", {})
    await emit_fn("thinking_end", {})

    if result.is_aborted:
        # Flow cancelled — respond with confirmation + feature suggestions
        await emit_fn("text_delta", {"delta": result.next_question or "Okay, no problem!"})
        abort_chips = [
            {"label": "Download statement", "value": "I want to download my statement"},
            {"label": "Check balance", "value": "How do I check my balance?"},
            {"label": "Card services", "value": "I need help with my card"},
        ]
        state_update = memory.get_state()
        state_update.pop("_flow", None)
        state_update.pop("suggested_actions", None)
        memory.update_state(state_update)
        await emit_fn("state", {k: v for k, v in memory.get_state().items() if k != "suggested_actions"})
        await emit_fn("finish", {"finishReason": "stop", "usage": {"promptTokens": 0, "completionTokens": 0}, "suggestedActions": abort_chips})
        memory.add_assistant_message(content=result.next_question)
        return

    if result.is_complete and result.completion_context:
        # Flow done — emit the completion response directly (no LLM needed)
        await emit_fn("text_delta", {"delta": result.completion_context})
        state_update = memory.get_state()
        state_update.pop("suggested_actions", None)
        memory.update_state(state_update)
        await emit_fn("state", {k: v for k, v in memory.get_state().items() if k != "suggested_actions"})
        await emit_fn("finish", {"finishReason": "stop", "usage": {"promptTokens": 0, "completionTokens": 0}, "suggestedActions": []})
        memory.add_assistant_message(content=result.completion_context)
        return

    # Next flow step — emit question + quick replies
    if result.next_question:
        await emit_fn("text_delta", {"delta": result.next_question})
        state_update = memory.get_state()
        state_update.pop("suggested_actions", None)
        memory.update_state(state_update)
        await emit_fn("state", {k: v for k, v in memory.get_state().items() if k != "suggested_actions"})
        await emit_fn("finish", {"finishReason": "stop", "usage": {"promptTokens": 0, "completionTokens": 0}, "suggestedActions": result.quick_replies or []})
        memory.add_assistant_message(content=result.next_question)


# ── Reset conversation ─────────────────────────────────────────────────────

@sio.event
async def reset_conversation(sid: str, data: dict[str, Any]) -> None:
    conversation_id = data.get("conversation_id") or _sid_to_conversation.get(sid, "")
    if not conversation_id:
        return

    clear_memory(conversation_id)
    _conversation_locks.pop(conversation_id, None)

    try:
        from app.db.connection import AsyncSessionLocal
        from app.db.repositories import save_messages
        async with AsyncSessionLocal() as session:
            await save_messages(session, conversation_id, [])
    except Exception as exc:
        logger.warning("DB clear failed for %s: %s", conversation_id, exc)

    logger.info("Conversation reset for %s (sid=%s)", conversation_id, sid)
    await sio.emit("conversation_reset", {"conversation_id": conversation_id}, to=sid)

