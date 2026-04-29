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

_FORCE_ESCALATION_CHIP_VALUES = {
    "connect me to an officer",
    "connect me to an agent",
    "i want to speak to a support agent",
    "speak to human",
    "need a human agent",
}


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


def _normalize_user_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _is_forced_escalation_chip(text: str) -> bool:
    return _normalize_user_text(text) in _FORCE_ESCALATION_CHIP_VALUES


def _format_log_fields(fields: dict[str, Any]) -> str:
    """Render key/value pairs into a compact single-line debug string."""
    parts: list[str] = []
    for k, v in fields.items():
        if isinstance(v, str):
            rendered = v.replace("\n", " ")
            if len(rendered) > 180:
                rendered = rendered[:180] + "..."
        else:
            rendered = str(v)
        parts.append(f"{k}={rendered}")
    return " | ".join(parts)


def _state_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """Small, stable state snapshot for logs."""
    flow = state.get("_flow") or {}
    return {
        "flow_name": flow.get("flow_name", "none"),
        "flow_step": flow.get("current_step_index", -1),
        "last_topic": state.get("_last_topic", ""),
        "clarification_count": state.get("_clarification_count", 0),
        "negative_sentiment_count": state.get("_negative_sentiment_count", 0),
    }


def _log_route(conversation_id: str, step: str, **fields: Any) -> None:
    """Centralized route logger so each decision point is easy to follow."""
    if not settings.route_debug_logs:
        return
    suffix = _format_log_fields(fields) if fields else ""
    if suffix:
        logger.info("[route][%s] %s | %s", conversation_id, step, suffix)
    else:
        logger.info("[route][%s] %s", conversation_id, step)


# ── Agent response guardrails ─────────────────────────────────────────────

# Patterns that indicate the LLM returned a raw error/technical response
_ERROR_JSON_RE = re.compile(
    r'^\s*\{[^}]*"error"\s*:\s*"[^"]*"\s*\}\s*$',
    re.DOTALL,
)
_OUT_OF_SCOPE_RE = re.compile(
    r"(no relevant banking knowledge|out of scope|not a banking|"
    r"cannot (assist|help) with (that|this)|i (don't|do not) have information on that)\b",
    re.IGNORECASE,
)

_FRIENDLY_FALLBACK = (
    "I'm sorry, I can only assist with banking-related questions. "
    "Please ask me about account services, loans, transfers, cards, or other banking topics. "
    "If you need further help, I can connect you with a support agent."
)


def _is_error_response(text: str) -> bool:
    """Return True if the assembled LLM response looks like a raw error/JSON."""
    stripped = text.strip()
    if _ERROR_JSON_RE.match(stripped):
        return True
    # Very short responses that are purely an error phrase
    if len(stripped) < 120 and _OUT_OF_SCOPE_RE.search(stripped):
        return True
    return False


def _make_guardrail_emit(base_emit_fn, conversation_id: str):
    """
    Wraps an emit_fn to intercept text_delta events.
    Accumulates streamed text; if the final assembled response is a raw error
    or out-of-scope JSON, suppresses it and emits a friendly fallback instead.
    """
    _buffer: list[str] = []
    _flushed: list[bool] = [False]  # mutable flag
    _finalized: list[bool] = [False]

    async def _guardrail_emit(event: str, payload: Any) -> None:
        if event == "text_delta":
            delta = payload.get("delta")
            if delta is None:
                delta = payload.get("text", "")
            if not isinstance(delta, str):
                delta = str(delta or "")
            _buffer.append(delta)
            assembled = "".join(_buffer)
            # Eagerly flush all buffered chunks once we have >120 chars of clearly valid text
            if not _flushed[0] and len(assembled) > 120 and not _is_error_response(assembled):
                _flushed[0] = True
                # Flush every buffered chunk in order (including the current one)
                for chunk in _buffer:
                    if chunk:
                        await base_emit_fn("text_delta", {"delta": chunk})
                return
            if _flushed[0]:
                await base_emit_fn("text_delta", {"delta": delta})
            # else: still buffering — wait for finish to decide
            return

        await base_emit_fn(event, payload)

    async def _finalize_guardrail() -> None:
        """
        Flush any buffered text for short responses.
        Needed because the socket agent loop returns usage to the router and does
        not emit a "finish" event itself.
        """
        if _finalized[0]:
            return
        _finalized[0] = True

        if _flushed[0]:
            return

        assembled = "".join(_buffer)
        if not assembled.strip():
            return

        if _is_error_response(assembled):
            logger.warning(
                "[guardrail][%s] suppressed error response, sending friendly fallback | raw=%r",
                conversation_id,
                assembled[:200],
            )
            await base_emit_fn("text_delta", {"delta": _FRIENDLY_FALLBACK})
            return

        for chunk in _buffer:
            if chunk:
                await base_emit_fn("text_delta", {"delta": chunk})

    return _guardrail_emit, _finalize_guardrail


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
        _add({"label": "Yes, explain more", "value": "Please explain that in more detail"})
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
    Routing decision tree (classifier-first, conversation-act authority).

    Order:
      1. Track negative sentiment (sync, fast)
      2. Emit thinking_start immediately
      3. Classify intent + conversation act (LLM, with last_bot + active_flow context)
      4. Route by assistant_action:
         a. close_conversation  → inline closure, no chips, return
         b. ask_clarification   → disambiguation question, yes/no chips, return
         c. abort_flow          → force-abort active flow + confirm, return
         d. re_explain          → re-explain loop, return
         e. Active flow exists  → FlowEngine.advance(), return
         f. Flow activation     → start flow, emit intro, return
         g. Else                → KB prefetch + full agent loop
    """
    from app.agent.intent_classifier import (
        classify_intent,
        detect_negative_sentiment,
    )
    from app.agent.flow_engine import FlowEngine

    # ── Seed session state from client (cross-request continuity) ─────────
    if session_state:
        memory.update_state(session_state)

    current_state = memory.get_state()
    last_topic = str(current_state.get("_last_topic", "") or "")
    _log_route(
        conversation_id,
        "start",
        msg_preview=_redact_pii(raw_message[:120]),
        msg_len=len(raw_message),
        state=_state_snapshot(current_state),
    )

    # ── 1. Track negative sentiment (sync, fast) ──────────────────────────
    if detect_negative_sentiment(raw_message):
        neg_count = int(current_state.get("_negative_sentiment_count", 0)) + 1
        current_state["_negative_sentiment_count"] = neg_count
        memory.update_state(current_state)

    # ── 2. INSTANT: emit thinking_start <100ms ────────────────────────────
    await emit_fn("thinking_start", {})
    route_started = time.perf_counter()

    # ── 3. Classify intent + conversation act ─────────────────────────────
    last_bot = _get_last_bot_message(memory)
    active_flow_name: str | None = current_state.get("_flow", {}).get("flow_name")
    is_first = len([m for m in memory.get_messages() if m.get("role") == "user"]) == 0
    _log_route(
        conversation_id,
        "pre_classify",
        is_first=is_first,
        active_flow=active_flow_name or "none",
        has_last_bot=bool(last_bot),
    )

    try:
        classification = await classify_intent(
            message=raw_message,
            conversation_history=memory.get_messages(),
            is_first_message=is_first,
            last_bot_message=last_bot,
            active_flow_name=active_flow_name,
            last_topic=last_topic,
        )
    except Exception as exc:
        logger.warning("Intent classification failed: %s — defaulting to general_faq", exc)
        from app.agent.intent_classifier import ClassificationResult
        from app.agent.intent_taxonomy import FALLBACK_INTENT
        intent_def = FALLBACK_INTENT
        classification = ClassificationResult(
            intent="general_faq", confidence=0.4,
            conversation_act="normal_banking_query",
            assistant_action="answer_with_rag",
            language="en", sentiment="neutral", reply_style="rag_answer",
            should_end_conversation=False, should_abort_flow=False,
            is_clarification=False, is_abort=False, is_negative_sentiment=False,
            suggested_profile=intent_def.profile, flow_name=None,
            required_slots=[], suggested_actions=intent_def.suggested_actions,
        )

    logger.info(
        "[%s] classify intent=%s act=%s action=%s conf=%.2f lang=%s",
        conversation_id,
        classification.intent,
        classification.conversation_act,
        classification.assistant_action,
        classification.confidence,
        classification.language,
    )
    _log_route(
        conversation_id,
        "classification",
        intent=classification.intent,
        act=classification.conversation_act,
        action=classification.assistant_action,
        confidence=f"{classification.confidence:.2f}",
        reply_style=classification.reply_style,
    )

    # ── Forced escalation chip/button path (deterministic HITL) ───────────
    if _is_forced_escalation_chip(raw_message):
        from app.tools.escalate_tool import EscalateInput, escalate_to_human

        result = await escalate_to_human(
            EscalateInput(
                reason="User explicitly requested escalation via quick-reply chip/button.",
                category="general",
            ),
            memory=memory,
        )
        final_text = result.split("Relay this to the user exactly:\n", 1)[-1].strip()
        memory.add_user_message(raw_message)
        await emit_fn("thinking_end", {})
        await emit_fn("text_delta", {"delta": final_text})
        await emit_fn("finish", {
            "finishReason": "stop",
            "usage": {"promptTokens": 0, "completionTokens": 0},
            "suggestedActions": [],
        })
        memory.add_assistant_message(content=final_text)
        _log_route(conversation_id, "finish_forced_escalation_chip")
        return

    # ── Classifier-directed escalation path (explicit user intent) ─────────
    if classification.assistant_action == "escalate" or classification.intent == "escalation_request":
        from app.tools.escalate_tool import EscalateInput, escalate_to_human

        result = await escalate_to_human(
            EscalateInput(
                reason="User explicitly requested a human officer/agent.",
                category="general",
            ),
            memory=memory,
        )
        final_text = result.split("Relay this to the user exactly:\n", 1)[-1].strip()
        memory.add_user_message(raw_message)
        await emit_fn("thinking_end", {})
        await emit_fn("text_delta", {"delta": final_text})
        await emit_fn("finish", {
            "finishReason": "stop",
            "usage": {"promptTokens": 0, "completionTokens": 0},
            "suggestedActions": [],
        })
        memory.add_assistant_message(content=final_text)
        _log_route(conversation_id, "finish_classifier_escalation")
        return

    # ── 4a. Conversation complete → inline closure, no chips ──────────────
    if classification.assistant_action == "close_conversation":
        if classification.language == "bn":
            closure = "আপনাকে সহায়তা করতে পেরে ভালো লাগলো! যেকোনো সময় প্রয়োজন হলে নির্দ্বিধায় আমাদের সাথে যোগাযোগ করুন! শুভদিন কাটসুন!"
        elif classification.language == "hinglish":
            closure = "Khushi hui aapki madad karke! Kabhi bhi zaroorat ho toh humse baat karein. Take care!"
        else:
            closure = "You're welcome! Feel free to reach out anytime. Have a great day!"

        memory.add_user_message(raw_message)
        await emit_fn("thinking_end", {})
        await emit_fn("text_delta", {"delta": closure})
        await emit_fn("state", {k: v for k, v in memory.get_state().items() if k != "suggested_actions"})
        await emit_fn("finish", {
            "finishReason": "stop",
            "usage": {"promptTokens": 0, "completionTokens": 0},
            "suggestedActions": [],
        })
        memory.add_assistant_message(content=closure)
        logger.info("[%s] Closed conversation (language=%s)", conversation_id, classification.language)
        _log_route(conversation_id, "finish_close", closure_preview=closure)
        return

    # ── 4b. Low-confidence disambiguation → ask clarifying question ───────
    if classification.assistant_action == "ask_clarification":
        if classification.language == "bn":
            disambig = "ক্ষমাকরুন, আমি নিশ্চিত হতে চাইছি — আপনি কি সারা হয়েছেন, নাকি আরও কোনো সাহায্যের প্রয়োজন আছে?"
        else:
            disambig = "Just to confirm — are you all done, or is there something else I can help you with?"

        yes_no_chips = [
            {"label": "Yes, I'm done", "value": "No, that's all I need"},
            {"label": "Help me with something else", "value": "I need help with something else"},
        ]
        memory.add_user_message(raw_message)
        await emit_fn("thinking_end", {})
        await emit_fn("text_delta", {"delta": disambig})
        await emit_fn("state", {k: v for k, v in memory.get_state().items() if k != "suggested_actions"})
        await emit_fn("finish", {
            "finishReason": "stop",
            "usage": {"promptTokens": 0, "completionTokens": 0},
            "suggestedActions": yes_no_chips,
        })
        memory.add_assistant_message(content=disambig)
        _log_route(
            conversation_id,
            "finish_disambiguation",
            reason="low_conf_terminal_action",
            chips=[c["label"] for c in yes_no_chips],
        )
        return

    # ── 4c. Abort active flow → force-abort + confirm ─────────────────────
    if classification.assistant_action == "abort_flow":
        engine = FlowEngine.from_session(current_state)
        if engine:
            _log_route(conversation_id, "branch_abort_flow", flow=active_flow_name or "none")
            await _handle_flow(
                raw_message=raw_message,
                memory=memory,
                emit_fn=emit_fn,
                engine=engine,
                profile_name=profile_name,
                extra_context=extra_context,
                conversation_id=conversation_id,
                force_abort=True,
            )
            return
        # No active flow to abort — fall through to normal routing
        _log_route(conversation_id, "branch_abort_flow_skipped", reason="no_active_flow")

    # ── 4d. Re-explain / clarification (classifier authority only) ────────
    if classification.is_clarification and last_bot:
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
            skip_initial_thinking=True,
        )

        if clarif_count >= 2:
            updated = memory.get_state()
            updated["suggested_actions"] = [
                {"label": "Connect me to an agent", "value": "I want to speak to a support agent"},
            ]
            memory.update_state(updated)
            await emit_fn("state", memory.get_state())
        _log_route(conversation_id, "finish_reexplain", clarif_count=clarif_count)
        return

    # ── 4e. Active flow exists → continue flow ────────────────────────────
    engine = FlowEngine.from_session(current_state)
    if engine:
        _log_route(conversation_id, "branch_continue_flow", flow=active_flow_name or "none")
        await _handle_flow(
            raw_message=raw_message,
            memory=memory,
            emit_fn=emit_fn,
            engine=engine,
            profile_name=profile_name,
            extra_context=extra_context,
            conversation_id=conversation_id,
            force_abort=False,
        )
        return

    # ── 4f. Store topic + check for flow activation ───────────────────────
    current_state["_last_topic"] = classification.intent
    memory.update_state(current_state)
    _log_route(
        conversation_id,
        "post_topic_store",
        last_topic=classification.intent,
        state=_state_snapshot(current_state),
    )

    if classification.flow_name and classification.confidence >= 0.65:
        new_engine = FlowEngine.activate(classification.flow_name, current_state)
        memory.update_state(current_state)
        _log_route(
            conversation_id,
            "branch_activate_flow",
            flow=classification.flow_name,
            confidence=f"{classification.confidence:.2f}",
        )

        if new_engine:
            intro_text, first_quick_replies = new_engine.get_intro()
            memory.add_user_message(raw_message)
            await emit_fn("thinking_end", {})
            await emit_fn("text_delta", {"delta": intro_text})
            state_update = memory.get_state()
            state_update.pop("suggested_actions", None)
            memory.update_state(state_update)
            await emit_fn("state", {k: v for k, v in memory.get_state().items() if k != "suggested_actions"})
            await emit_fn("finish", {"finishReason": "stop", "usage": {"promptTokens": 0, "completionTokens": 0}, "suggestedActions": first_quick_replies or []})
            memory.add_assistant_message(content=intro_text)
            _log_route(conversation_id, "finish_flow_intro", quick_replies=len(first_quick_replies or []))
            return

    # ── 4g. KB prefetch + full agent loop ────────────────────────────────
    kb_task: asyncio.Task = asyncio.create_task(_prefetch_kb(raw_message))
    _log_route(conversation_id, "branch_agent_loop", reason="no_flow_or_special_action")

    async def _push_chips_bg() -> list[dict]:
        chips = _build_chips(classification)
        await emit_fn("chips_update", {"suggestedActions": chips})
        return chips

    chip_task: asyncio.Task = asyncio.create_task(_push_chips_bg())

    kb_wait_started = time.perf_counter()
    try:
        kb_context, kb_confidence = await asyncio.wait_for(kb_task, timeout=8.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        kb_context, kb_confidence = "", 0.0
        logger.warning("[%s] KB prefetch timed out — LLM will use tools if needed", conversation_id)
    kb_wait_ms = (time.perf_counter() - kb_wait_started) * 1000
    logger.info(
        "[%s] kb_prefetch wait=%.0f ms confidence=%.2f context_len=%d",
        conversation_id, kb_wait_ms, kb_confidence, len(kb_context),
    )
    _log_route(
        conversation_id,
        "kb_prefetch_done",
        wait_ms=f"{kb_wait_ms:.0f}",
        kb_confidence=f"{kb_confidence:.2f}",
        kb_context_len=len(kb_context),
    )

    enriched_context = dict(extra_context or {})
    enriched_context.update({
        "_last_topic": current_state.get("_last_topic", ""),
        "_negative_sentiment_count": current_state.get("_negative_sentiment_count", 0),
        "_clarification_count": current_state.get("_clarification_count", 0),
        "_kb_context": kb_context,
        "_kb_confidence": kb_confidence,
        "_assistant_action": classification.assistant_action,
        "_conversation_act": classification.conversation_act,
        "_classifier_confidence": classification.confidence,
        "_last_bot_message": last_bot,
    })

    if is_first or classification.intent == "greeting":
        current_state["suggested_actions"] = classification.suggested_actions
        memory.update_state(current_state)

    guarded_emit, finalize_guardrail = _make_guardrail_emit(emit_fn, conversation_id)
    usage = await run_agent_loop_with_emitter(
        message=raw_message,
        conversation_id=conversation_id,
        memory=memory,
        emit_fn=guarded_emit,
        profile_name=profile_name,
        context=enriched_context,
        session_state=None,
        suggested_actions=classification.suggested_actions or [],
        skip_initial_thinking=True,
    )
    await finalize_guardrail()
    logger.info(
        "[%s] agent_loop total_route=%.0f ms",
        conversation_id,
        (time.perf_counter() - route_started) * 1000,
    )
    _log_route(
        conversation_id,
        "agent_loop_done",
        prompt_tokens=usage.get("promptTokens", 0),
        completion_tokens=usage.get("completionTokens", 0),
    )

    if not chip_task.done():
        try:
            await asyncio.wait_for(asyncio.shield(chip_task), timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            logger.warning("[%s] Chip task did not complete in time", conversation_id)

    last_answer = _get_last_bot_message(memory) or ""
    final_chips = _build_chips(classification, answer_tail=last_answer[-200:])

    await emit_fn("finish", {
        "finishReason": "stop",
        "usage": {
            "promptTokens": usage.get("promptTokens", 0),
            "completionTokens": usage.get("completionTokens", 0),
        },
        "suggestedActions": final_chips,
    })
    _log_route(
        conversation_id,
        "finish_agent",
        final_chip_count=len(final_chips),
        chip_labels=[c.get("label", "") for c in final_chips],
    )


async def _handle_flow(
    raw_message: str,
    memory,
    emit_fn,
    engine,
    profile_name: str,
    extra_context: dict | None,
    conversation_id: str,
    force_abort: bool = False,
) -> None:
    """Process a message against an active flow."""
    current_state = memory.get_state()
    flow_state = current_state.get("_flow", {})
    if settings.route_debug_logs:
        logger.info(
            "[flow][%s] enter | flow=%s | step=%s | force_abort=%s | input=%r",
            conversation_id,
            flow_state.get("flow_name", "none"),
            flow_state.get("current_step_index", -1),
            force_abort,
            _redact_pii(raw_message[:120]),
        )
    result = engine.advance(
        user_input=raw_message,
        session_state=current_state,
        bank_name=settings.bank_name,
        force_abort=force_abort,
    )
    memory.update_state(current_state)
    if settings.route_debug_logs:
        logger.info(
            "[flow][%s] result | aborted=%s | complete=%s | next_question=%r | quick_replies=%d",
            conversation_id,
            result.is_aborted,
            result.is_complete,
            (result.next_question or "")[:140],
            len(result.quick_replies or []),
        )

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

