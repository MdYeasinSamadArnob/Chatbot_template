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
    sources               — { sources: [...] }
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
from collections import OrderedDict
from contextlib import suppress
import hashlib
import json
import logging
import re
import time
from typing import Any

import socketio

from app.agent.core import run_agent_loop_with_emitter, run_reexplain_loop_with_emitter, _visible_sources
from app.agent.memory import clear_memory, get_or_create_memory
from app.agent.profiles import list_profiles
from app.config import settings

logger = logging.getLogger(__name__)

# ── Response-level cache ───────────────────────────────────────────────────────
# Key: SHA1(normalised_message + intent)  Value: {answer, sources, chips, ts}
# TTL: 300 s   Max entries: 256
# Only caches answer_with_rag hits where kb_conf >= 0.75.
_RESPONSE_CACHE: OrderedDict[str, dict] = OrderedDict()
_CACHE_TTL_S: float = 300.0
_CACHE_MAX: int = 256

def _cache_key(message: str, intent: str) -> str:
    norm = " ".join(message.lower().split())
    return hashlib.sha1(f"{norm}\x00{intent}".encode()).hexdigest()

def _cache_get(key: str) -> dict | None:
    entry = _RESPONSE_CACHE.get(key)
    if entry is None:
        return None
    if time.time() - entry["ts"] > _CACHE_TTL_S:
        _RESPONSE_CACHE.pop(key, None)
        return None
    # LRU: move to end
    _RESPONSE_CACHE.move_to_end(key)
    return entry

def _cache_put(key: str, answer: str, sources: list, chips: list) -> None:
    if key in _RESPONSE_CACHE:
        _RESPONSE_CACHE.move_to_end(key)
    _RESPONSE_CACHE[key] = {"answer": answer, "sources": sources, "chips": chips, "ts": time.time()}
    while len(_RESPONSE_CACHE) > _CACHE_MAX:
        _RESPONSE_CACHE.popitem(last=False)


def _extract_kb_prefetch_payload(result: str) -> tuple[str, float, list]:
    """Handle both legacy markdown and structured JSON from KB search tool.
    Returns (context_text, confidence, sources).

    Confidence uses multi-signal gating (global-standard pattern):
      - reranker_score: cross-encoder relevance of best result (primary signal)
      - result count: at least 2 results = more coverage
      - keyword overlap: query tokens found in top document (lexical confirmation)

    Formula: 0.6*reranker_signal + 0.25*count_signal + 0.15*keyword_signal
    This replaces the naive count-only confidence (0.8 if n>=2, else 0.55).
    """
    try:
        payload = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        payload = None

    if isinstance(payload, dict) and payload.get("kind") == "kb_search_result":
        context_text = payload.get("context_markdown")
        if not isinstance(context_text, str) or not context_text.strip():
            return "", 0.0, []

        sources = payload.get("sources")
        if isinstance(sources, list) and sources:
            n = len(sources)

            # Signal 1: cross-encoder reranker score (range ~-10 to +10, higher = better).
            # Normalise: score > 5 = excellent, < -3 = poor. Clamp to [0, 1].
            top_reranker = max(
                (float(s.get("reranker_score", 0.0)) for s in sources),
                default=0.0,
            )
            reranker_signal = max(0.0, min(1.0, (top_reranker + 3.0) / 8.0))

            # Signal 2: result count (2+ = better coverage)
            count_signal = 1.0 if n >= 2 else 0.5

            # Signal 3: keyword overlap between context text and... nothing yet here;
            # we don't have the original query at this point. Derived from reranker.
            # Use whether ANY result has a positive reranker score as a proxy.
            keyword_signal = 1.0 if top_reranker > 0 else 0.3

            confidence = (
                0.60 * reranker_signal
                + 0.25 * count_signal
                + 0.15 * keyword_signal
            )
            # Hard floor: if reranker says everything is poor (<-3), cap at 0.4
            if top_reranker < -3.0:
                confidence = min(confidence, 0.4)

        else:
            sources = []
            confidence = 0.4
        return context_text, confidence, sources

    text = result or ""
    if not text or "unavailable" in text.lower() or "No specific articles" in text:
        return "", 0.0, []

    match = re.search(r"Found (\d+) relevant", text)
    if match:
        n = int(match.group(1))
        confidence = 0.8 if n >= 2 else 0.55
    else:
        confidence = 0.4
    return text, confidence, []


# Words that, on their own, constitute a genuine farewell.
# Plain Python set — no regex, no hardcoded language patterns.
_FAREWELL_TOKENS: frozenset[str] = frozenset({
    "thanks", "thank", "you", "bye", "goodbye", "done", "ok", "okay",
    "alright", "all", "that's", "thats", "see", "later", "good", "day",
    "night", "take", "care", "nothing", "else", "no", "more",
})


def _is_real_question(message: str) -> bool:
    """Return True when the message is a substantive query, not a pure farewell.

    The LLM classifier is the primary gate; this is a cheap safety net only.
    Logic: messages longer than 5 tokens, containing '?', or whose tokens are
    not ALL farewell words are treated as real questions — no regex needed.
    """
    msg = (message or "").strip()
    if not msg:
        return False
    if "?" in msg:
        return True
    tokens = [t.lower().strip(".,!'") for t in msg.split()]
    if len(tokens) > 5:
        return True
    # Every token must be a known farewell word to treat this as a close
    return not all(t in _FAREWELL_TOKENS for t in tokens)


def _fallback_handoff_text_for_message(message: str, language: str = "en") -> str:
    import random
    msg_lc = (message or "").lower()
    is_bn = language == "bn" or bool(re.search(r"[\u0980-\u09FF]", message or ""))

    _POOLS: list[tuple[str, list[str], list[str]]] = [
        (
            r"transfer|send|remit",
            [
                "Let me find the right transfer steps for you.",
                "Checking the transfer options for your request.",
                "Looking up how to transfer \u2014 one moment.",
            ],
            [
                "\u099f\u09cd\u09b0\u09be\u09a8\u09cd\u09b8\u09ab\u09be\u09b0\u09c7\u09b0 \u09b8\u09a0\u09bf\u0995 \u09a4\u09a5\u09cd\u09af \u0996\u09c1\u0981\u099c\u099b\u09bf\u0964",
                "\u0986\u09aa\u09a8\u09be\u09b0 \u099f\u09cd\u09b0\u09be\u09a8\u09cd\u09b8\u09ab\u09be\u09b0 \u0985\u09a8\u09c1\u09b0\u09cb\u09a7\u09c7\u09b0 \u09a4\u09a5\u09cd\u09af \u09a6\u09c7\u0996\u099b\u09bf\u0964",
            ],
        ),
        (
            r"balance|statement|history",
            [
                "Pulling together the account details for you.",
                "Let me check that account information.",
                "Looking up your account info now.",
            ],
            [
                "\u0985\u09cd\u09af\u09be\u0995\u09be\u0989\u09a8\u09cd\u099f\u09c7\u09b0 \u09a4\u09a5\u09cd\u09af \u09a6\u09c7\u0996\u099b\u09bf\u0964",
                "\u09ac\u09cd\u09af\u09be\u09b2\u09c7\u09a8\u09cd\u09b8 \u09b8\u0982\u0995\u09cd\u09b0\u09be\u09a8\u09cd\u09a4 \u09a4\u09a5\u09cd\u09af \u0996\u09c1\u0981\u099c\u099b\u09bf\u0964",
            ],
        ),
        (
            r"card|debit|credit|atm|pin",
            [
                "Looking up the card-related steps for you.",
                "Checking card information \u2014 just a moment.",
                "Let me find the right card details.",
            ],
            [
                "\u0995\u09be\u09b0\u09cd\u09a1 \u09b8\u0982\u0995\u09cd\u09b0\u09be\u09a8\u09cd\u09a4 \u09a4\u09a5\u09cd\u09af \u0996\u09c1\u0981\u099c\u099b\u09bf\u0964",
                "\u0995\u09be\u09b0\u09cd\u09a1\u09c7\u09b0 \u09a7\u09be\u09aa\u0997\u09c1\u09b2\u09cb \u09a6\u09c7\u0996\u099b\u09bf\u0964",
            ],
        ),
        (
            r"loan|emi|installment",
            [
                "Checking the loan details that match your question.",
                "Looking up loan information for you.",
                "Let me find the relevant loan details.",
            ],
            [
                "\u098b\u09a3 \u09b8\u0982\u0995\u09cd\u09b0\u09be\u09a8\u09cd\u09a4 \u09a4\u09a5\u09cd\u09af \u09a6\u09c7\u0996\u099b\u09bf\u0964",
                "\u09b2\u09cb\u09a8\u09c7\u09b0 \u09ac\u09bf\u09b8\u09cd\u09a4\u09be\u09b0\u09bf\u09a4 \u0996\u09c1\u0981\u099c\u099b\u09bf\u0964",
            ],
        ),
        (
            r"account|open|close|kyc",
            [
                "Checking the account-service details for you.",
                "Looking up how to help with your account.",
                "Finding the right account information.",
            ],
            [
                "\u0985\u09cd\u09af\u09be\u0995\u09be\u0989\u09a8\u09cd\u099f \u09b8\u09c7\u09ac\u09be\u09b0 \u09a4\u09a5\u09cd\u09af \u09a6\u09c7\u0996\u099b\u09bf\u0964",
                "\u0985\u09cd\u09af\u09be\u0995\u09be\u0989\u09a8\u09cd\u099f \u09b8\u0982\u0995\u09cd\u09b0\u09be\u09a8\u09cd\u09a4 \u09a4\u09a5\u09cd\u09af \u0996\u09c1\u0981\u099c\u099b\u09bf\u0964",
            ],
        ),
    ]
    for pattern, en_pool, bn_pool in _POOLS:
        if re.search(rf"\b({pattern})\b", msg_lc):
            return random.choice(bn_pool if is_bn else en_pool)

    default_en = [
        "Let me find the right information for you.",
        "Checking the details for your request.",
        "Looking that up for you now.",
    ]
    default_bn = [
        "\u0986\u09aa\u09a8\u09be\u09b0 \u099c\u09a8\u09cd\u09af \u09b8\u09a0\u09bf\u0995 \u09a4\u09a5\u09cd\u09af\u099f\u09bf \u0996\u09c1\u0981\u099c\u099b\u09bf\u0964",
        "\u0986\u09aa\u09a8\u09be\u09b0 \u0985\u09a8\u09c1\u09b0\u09cb\u09a7\u09c7\u09b0 \u09ac\u09bf\u09b8\u09cd\u09a4\u09be\u09b0\u09bf\u09a4 \u09a6\u09c7\u0996\u099b\u09bf\u0964",
    ]
    return random.choice(default_bn if is_bn else default_en)


# ── Progressive thinking status steps ─────────────────────────────────────

_STATUS_STEPS: dict[str, tuple[list[str], list[str]]] = {
    "fund_transfer": (
        ["Searching transfer methods\u2026", "Found relevant guides\u2026", "Preparing step-by-step instructions\u2026"],
        ["\u099f\u09cd\u09b0\u09be\u09a8\u09cd\u09b8\u09ab\u09be\u09b0 \u09aa\u09a6\u09cd\u09a7\u09a4\u09bf \u0996\u09c1\u0981\u099c\u099b\u09bf\u2026", "\u09aa\u09cd\u09b0\u09be\u09b8\u0999\u09cd\u0997\u09bf\u0995 \u0997\u09be\u0987\u09a1 \u09aa\u09c7\u09af\u09bc\u09c7\u099b\u09bf\u2026", "\u09a7\u09be\u09aa\u0997\u09c1\u09b2\u09cb \u09aa\u09cd\u09b0\u09b8\u09cd\u09a4\u09c1\u09a4 \u0995\u09b0\u099b\u09bf\u2026"],
    ),
    "card_services": (
        ["Looking up card procedures\u2026", "Checking card information\u2026", "Almost ready\u2026"],
        ["\u0995\u09be\u09b0\u09cd\u09a1 \u09b8\u0982\u0995\u09cd\u09b0\u09be\u09a8\u09cd\u09a4 \u09a4\u09a5\u09cd\u09af \u0996\u09c1\u0981\u099c\u099b\u09bf\u2026", "\u09aa\u09cd\u09b0\u09be\u09b8\u0999\u09cd\u0997\u09bf\u0995 \u09a4\u09a5\u09cd\u09af \u09aa\u09c7\u09af\u09bc\u09c7\u099b\u09bf\u2026", "\u0989\u09a4\u09cd\u09a4\u09b0 \u09aa\u09cd\u09b0\u09b8\u09cd\u09a4\u09c1\u09a4 \u0995\u09b0\u099b\u09bf\u2026"],
    ),
    "account_inquiry": (
        ["Pulling account details\u2026", "Found relevant information\u2026", "Preparing your answer\u2026"],
        ["\u0985\u09cd\u09af\u09be\u0995\u09be\u0989\u09a8\u09cd\u099f\u09c7\u09b0 \u09a4\u09a5\u09cd\u09af \u0996\u09c1\u0981\u099c\u099b\u09bf\u2026", "\u09aa\u09cd\u09b0\u09be\u09b8\u0999\u09cd\u0997\u09bf\u0995 \u09a4\u09a5\u09cd\u09af \u09aa\u09c7\u09af\u09bc\u09c7\u099b\u09bf\u2026", "\u0989\u09a4\u09cd\u09a4\u09b0 \u09aa\u09cd\u09b0\u09b8\u09cd\u09a4\u09c1\u09a4 \u0995\u09b0\u099b\u09bf\u2026"],
    ),
    "loan_services": (
        ["Checking loan information\u2026", "Found loan details\u2026", "Preparing your answer\u2026"],
        ["\u098b\u09a3 \u09b8\u0982\u0995\u09cd\u09b0\u09be\u09a8\u09cd\u09a4 \u09a4\u09a5\u09cd\u09af \u0996\u09c1\u0981\u099c\u099b\u09bf\u2026", "\u09ac\u09bf\u09b8\u09cd\u09a4\u09be\u09b0\u09bf\u09a4 \u09a4\u09a5\u09cd\u09af \u09aa\u09c7\u09af\u09bc\u09c7\u099b\u09bf\u2026", "\u0989\u09a4\u09cd\u09a4\u09b0 \u09aa\u09cd\u09b0\u09b8\u09cd\u09a4\u09c1\u09a4 \u0995\u09b0\u099b\u09bf\u2026"],
    ),
}
_STATUS_DEFAULT_EN = ["Searching knowledge base\u2026", "Found relevant articles\u2026", "Preparing your answer\u2026"]
_STATUS_DEFAULT_BN = ["\u09a4\u09a5\u09cd\u09af \u0996\u09c1\u0981\u099c\u099b\u09bf\u2026", "\u09aa\u09cd\u09b0\u09be\u09b8\u0999\u09cd\u0997\u09bf\u0995 \u09a4\u09a5\u09cd\u09af \u09aa\u09c7\u09af\u09bc\u09c7\u099b\u09bf\u2026", "\u0986\u09aa\u09a8\u09be\u09b0 \u0989\u09a4\u09cd\u09a4\u09b0 \u09aa\u09cd\u09b0\u09b8\u09cd\u09a4\u09c1\u09a4 \u0995\u09b0\u099b\u09bf\u2026"]


def _get_status_steps(intent: str, language: str) -> list[str]:
    is_bn = language == "bn"
    en_steps, bn_steps = _STATUS_STEPS.get(intent, (_STATUS_DEFAULT_EN, _STATUS_DEFAULT_BN))
    return bn_steps if is_bn else en_steps


async def _run_status_loop(
    emit_fn,
    steps: list,
    stop_event,
    interval: float = 1.8,
) -> None:
    """Emit progressive thinking_status labels until stop_event fires or steps exhausted."""
    import asyncio as _asyncio
    for step in steps:
        if stop_event.is_set():
            return
        try:
            await emit_fn("thinking_status", {"label": step})
        except Exception:
            return
        deadline = _asyncio.get_event_loop().time() + interval
        while not stop_event.is_set():
            remaining = deadline - _asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            await _asyncio.sleep(min(0.1, remaining))


def _sanitize_handoff_text(text: str, fallback: str) -> str:
    value = (text or "").strip().strip('"\'')
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"^(assistant|bot)\s*:\s*", "", value, flags=re.IGNORECASE)
    if not value:
        return fallback
    if value.endswith("?"):
        value = value.rstrip("?!. ") + "."
    if len(value) > 140:
        value = value[:140].rsplit(" ", 1)[0].rstrip(" ,.;:") + "."
    return value or fallback


async def _generate_dynamic_handoff_text(message: str) -> str:
    """
    Use the fast Granite classifier model as a tiny acknowledgment generator.
    This is separate from the heavier classifier JSON prompt, so the first
    streamed sentence can stay aligned with the user's exact request.
    """
    fallback = _fallback_handoff_text_for_message(message)
    try:
        from litellm import acompletion

        model = settings.classifier_model or settings.model_name
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are writing the assistant's first short acknowledgment sentence "
                        "for a banking chatbot. Reply with exactly one plain-text sentence. "
                        "Briefly reflect the user's request and say you are checking or preparing "
                        "the right information. Do not answer the question yet. "
                        "No markdown. No bullets. No JSON. No role labels."
                    ),
                },
                {
                    "role": "user",
                    "content": f"User message: {message}",
                },
            ],
            "temperature": 0.1,
            "stream": False,
            "max_tokens": 24,
        }

        is_ollama = (
            "11434" in settings.ollama_base_url
            or "ollama" in settings.ollama_base_url.lower()
        )
        if is_ollama and "/" not in model:
            kwargs["model"] = f"ollama/{model}"
        if "ollama/" in kwargs["model"]:
            kwargs["api_base"] = settings.ollama_base_url
            if not settings.llm_thinking:
                kwargs["extra_body"] = {"think": False}

        response = await acompletion(**kwargs)
        content = (response.choices[0].message.content or "").strip()
        return _sanitize_handoff_text(content, fallback)
    except Exception as exc:
        logger.debug("Dynamic handoff generation failed: %s", exc)
        return fallback

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


_SMALL_TALK_ROUTE_RE = re.compile(
    r"\b(how\s+are\s+you|kemon\s+acho|kemon\s+asen|"
    r"speak\s+in\s+bangla|speak\s+bangla|banglay\s+kotha|"
    r"can\s+you\s+speak\s+(bangla|bengali)|"
    r"amar\s+sathe\s+bangla(te)?\s+kotha\s+bolo)\b",
    re.IGNORECASE,
)


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
    import hashlib as _hashlib
    import time as _time
    import urllib.parse
    import uuid as uuid_module

    t0 = _time.monotonic()

    query_string = environ.get("QUERY_STRING", "")
    params = dict(urllib.parse.parse_qsl(query_string))

    # ── Parse and sanitize identity params ────────────────────────────
    from app.session.auth import (
        sanitize_user_id,
        sanitize_username,
        sanitize_screen_context,
        verify_user_identity,
    )
    from app.session.redis_store import get_redis_store

    raw_user_id      = params.get("user_id", "")
    raw_username     = params.get("username", "")
    raw_screen_ctx   = params.get("screen_context", "")
    raw_timestamp    = params.get("timestamp", "")
    raw_signature    = params.get("signature", "")
    raw_conv_id      = params.get("conversation_id", "")

    user_id       = sanitize_user_id(raw_user_id)
    username      = sanitize_username(raw_username)
    screen_context = sanitize_screen_context(raw_screen_ctx)

    is_authenticated = bool(user_id)

    # ── HMAC verification for authenticated users ──────────────────────
    if is_authenticated:
        if not verify_user_identity(
            user_id, username, screen_context,
            raw_timestamp, raw_signature,
            settings.session_secret,
        ):
            logger.warning(
                "[connect] HMAC verification failed for user_id=%r — disconnecting sid=%s",
                user_id[:16], sid,
            )
            await sio.disconnect(sid)
            return

    # ── Conversation resolution ────────────────────────────────────────
    redis = get_redis_store()
    conv_source = "guest"
    conversation_id: str = ""

    if is_authenticated:
        from app.db.connection import AsyncSessionLocal
        from app.db.repositories import (
            get_conversation_by_id_and_user,
            get_latest_conversation_for_user,
            create_user_conversation,
            has_previous_conversations,
        )

        if raw_conv_id:
            # Reload path: client supplied a conv_id from localStorage.
            # Strictly verify ownership before trusting it.
            async with AsyncSessionLocal() as db_session:
                verified = await get_conversation_by_id_and_user(
                    db_session, raw_conv_id, user_id
                )
            if verified:
                conversation_id = verified
                conv_source = "db"
            else:
                # conv_id doesn't belong to this user — treat as fresh launch
                logger.warning(
                    "[connect] conv_id %r not owned by user_id_hash=%s — creating new",
                    raw_conv_id[:8], _hashlib.sha256(user_id.encode()).hexdigest()[:8],
                )

        if not conversation_id:
            # Fresh launch: always create a new conversation
            async with AsyncSessionLocal() as db_session:
                conversation_id = await create_user_conversation(
                    db_session, user_id, username, screen_context
                )
            conv_source = "new"
            # Update Redis user→conv mapping
            await redis.set_user_conv(user_id, conversation_id)
            await redis.set_user_profile(user_id, username, screen_context)

        # Check if the user has previous conversations (for "Continue" button)
        has_prev = False
        prev_conv_id: str | None = None
        if conv_source == "new":
            async with AsyncSessionLocal() as db_session:
                prev_conv_id = await get_latest_conversation_for_user(db_session, user_id)
            # prev_conv_id is the most recent, but if this IS a reload it equals current
            if prev_conv_id and prev_conv_id != conversation_id:
                has_prev = True
            else:
                prev_conv_id = None
    else:
        # Guest: use client-supplied UUID or generate one
        conversation_id = raw_conv_id or str(uuid_module.uuid4())
        has_prev = False
        prev_conv_id = None

    _sid_to_conversation[sid] = conversation_id

    latency_ms = int((_time.monotonic() - t0) * 1000)
    user_hash = _hashlib.sha256(user_id.encode()).hexdigest()[:8] if user_id else "guest"
    logger.info(
        "[connect] user_hash=%s conv=%s source=%s resume=%s latency=%dms sid=%s",
        user_hash, conversation_id, conv_source, raw_conv_id != "", latency_ms, sid,
    )

    # ── Load memory ────────────────────────────────────────────────────
    memory = get_or_create_memory(conversation_id, settings.memory_persist_dir)

    # Session load: try Redis first (hot path), fall back to DB + rehydrate
    if redis.available:
        cached_msgs = await redis.get_session(conversation_id)
        if cached_msgs is not None:
            # Redis hit — restore messages directly without DB round-trip
            memory._messages = cached_msgs  # noqa: SLF001
            logger.debug("[connect] session loaded from Redis for conv=%s", conversation_id)
        else:
            # Redis miss — load from DB then rehydrate Redis (SET NX)
            await memory.load_from_db()
            await redis.set_session(conversation_id, memory.get_messages(), nx=True)
    else:
        await memory.load_from_db()

    # Set user context on the memory object so prompts.py can use it
    memory.set_user_context(user_id or None, username or None, screen_context or None)

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
                    memory.replace_state(state)
            except (ValueError, TypeError):
                pass

    await sio.emit("connected", {"conversation_id": conversation_id}, to=sid)

    # Emit user_context so the frontend can personalise header / quick actions
    await sio.emit(
        "user_context",
        {
            "user_id": user_id or None,
            "username": username or None,
            "screen_context": screen_context or None,
            "is_guest": not is_authenticated,
            "conv_id": conversation_id,
            "has_previous_session": has_prev,
            "prev_conv_id": prev_conv_id,
        },
        to=sid,
    )

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


@sio.event
async def load_previous_session(sid: str, data: dict[str, Any]) -> None:
    """
    Load the last 50 messages from a previous conversation and emit them as a
    single 'history_payload' event.  The frontend replaces (not appends) its
    message list with this payload.

    Requires: { prev_conv_id: str }
    The ownership check relies on the user_id stored in memory for this sid.
    """
    conversation_id = _sid_to_conversation.get(sid, "")
    if not conversation_id:
        return

    prev_conv_id = str(data.get("prev_conv_id", "")).strip()
    if not prev_conv_id:
        await sio.emit("error", {"message": "prev_conv_id is required."}, to=sid)
        return

    memory = get_or_create_memory(conversation_id, settings.memory_persist_dir)
    user_ctx = memory.get_user_context()
    user_id = user_ctx.get("user_id")

    if not user_id:
        await sio.emit("error", {"message": "Not authenticated."}, to=sid)
        return

    try:
        from app.db.connection import AsyncSessionLocal
        from app.db.repositories import (
            get_conversation_by_id_and_user,
            get_last_n_messages,
        )
        async with AsyncSessionLocal() as db_session:
            # Strict ownership check
            verified = await get_conversation_by_id_and_user(db_session, prev_conv_id, user_id)
            if not verified:
                await sio.emit("error", {"message": "Previous session not found."}, to=sid)
                return
            msgs = await get_last_n_messages(db_session, prev_conv_id, n=50)

        await sio.emit("history_payload", {"messages": msgs, "prev_conv_id": prev_conv_id}, to=sid)
        logger.info(
            "[load_previous_session] conv=%s loaded %d msgs from prev_conv=%s",
            conversation_id, len(msgs), prev_conv_id,
        )
    except Exception as exc:
        logger.warning("[load_previous_session] failed: %s", exc)
        await sio.emit("error", {"message": "Could not load previous session."}, to=sid)


async def _persist(memory) -> None:
    """Flush memory to PostgreSQL (source of truth) then update Redis cache."""
    try:
        await memory.save_to_db()
    except Exception as exc:
        logger.warning("Background persist failed: %s", exc)
        return  # Don't attempt Redis if DB failed

    # Write-through to Redis (best-effort, never raises)
    try:
        from app.session.redis_store import get_redis_store
        redis = get_redis_store()
        if redis.available:
            msgs = memory.get_messages()
            await redis.set_session(memory.conversation_id, msgs, nx=False)
    except Exception as exc:
        logger.warning("Redis write-through after persist failed: %s", exc)


# ── Chat message handler ───────────────────────────────────────────────────

@sio.event
async def chat_message(sid: str, data: dict[str, Any]) -> None:
    """
    Main entry point. Runs the full routing decision tree before
    delegating to the appropriate handler.
    """
    # Always use the server-authoritative conversation_id for this sid.
    # The client-supplied conversation_id is intentionally ignored here to
    # prevent a stale localStorage value from routing to the wrong memory.
    conversation_id = _sid_to_conversation.get(sid, "")
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


# ── Chip relevance helpers ───────────────────────────────────────────────

# Detects when the agent's answer signals it found no KB content for the topic.
# Used to suppress misleading intent-specific chips (e.g. "Apply for loan"
# after the agent said it has no loan info).
_NO_KB_DATA_RE = re.compile(
    r"("
    r"don['’]?t have (specific |)(information|info|details|data)"
    r"|(no|not|n['’]t) (specific |relevant |)(information|info|articles|content|data) (on|about|for|regarding)"
    r"|not (available|found) in (my |)(current |)(knowledge|database|knowledge base)"
    r"|cannot find (any |specific |)(information|info|details)"
    r"|contact .{0,40}support"
    r"|contact .{0,40}helpline"
    r"|unfortunately[, ].{0,30}(don['’]?t|do not|cannot)"
    r"|i['’]?m (sorry|afraid)[,.] ?(but |)(i |)?(don['’]?t|do not|cannot|have no)"
    r")",
    re.IGNORECASE,
)

# Generic navigation chips shown when KB had no relevant data.
# These map to topics that are actually documented in the knowledge base.
_NO_DATA_FALLBACK_CHIPS: list[dict] = [
    {"label": "Transfer money",    "value": "How do I transfer money to another account?"},
    {"label": "Check my balance",  "value": "How do I check my balance?"},
    {"label": "Card services",     "value": "I need help with my card"},
    {"label": "Account services",  "value": "How do I open a bank account?"},
    {"label": "Speak to an agent", "value": "I want to speak to a support agent"},
]


# ── KB pre-fetch helper ────────────────────────────────────────────────────

async def _prefetch_kb(query: str) -> tuple[str, float, list]:
    """
    Pre-fetch knowledge base context in parallel with intent classification.
    Returns (context_text, confidence_score, sources).
    Confidence: 0.8 = strong (2+ results), 0.55 = partial (1 result),
                0.4 = keyword fallback, 0.0 = no match / error.
    When embeddings are degraded (sparse-only mode), confidence is capped at
    0.55 so sparse-only results never trigger the strong_kb_answer_ready path,
    which would surface irrelevant keyword-matched articles as authoritative.
    """
    try:
        from app.tools.vector_search import (
            search_banking_knowledge,
            VectorSearchInput,
            embedding_backend_degraded,
        )
        result = await search_banking_knowledge(VectorSearchInput(query=query, top_k=settings.kb_prefetch_top_k))
        context_text, confidence, sources = _extract_kb_prefetch_payload(result)
        # If the embedding model was unavailable during this prefetch, the search
        # used sparse BM25 only.  BM25 matches on keywords ("account", "money")
        # and returns semantically wrong results for transfer queries.  Cap
        # confidence so the agent uses its tool loop instead.
        if embedding_backend_degraded():
            capped = min(confidence, 0.55)
            if capped < confidence:
                logger.info(
                    "[KB prefetch] embedding degraded — capping confidence %.2f → %.2f (sparse-only results)",
                    confidence, capped,
                )
            confidence = capped
        logger.debug("[KB prefetch] confidence=%.2f result_len=%d sources=%d", confidence, len(context_text), len(sources))
        return context_text, confidence, sources
    except Exception as exc:
        logger.warning("KB prefetch failed: %s", exc)
        return "", 0.0, []


# ── Chip builder helper ────────────────────────────────────────────────────

def _build_chips(classification, answer_tail: str = "") -> list[dict]:
    """
    Build quick-reply chips from:
      1. Yes/No detection on last 200 chars of answer
      2. next_likely intent chips (LLM-predicted follow-ups)  ─┐ skipped when
      3. Current intent's suggested_actions                    ─┘ agent had no KB data
    Deduplicates by 'value', caps at 6.

    When the answer indicates the agent found no relevant KB content ("I don't
    have specific information..."), steps 2 and 3 are replaced with generic
    navigation chips that map to topics actually in the knowledge base.  This
    prevents misleading chips like "Apply for loan" appearing after an answer
    that admitted there is no loan information available.
    """
    from app.agent.intent_taxonomy import INTENTS
    chips: list[dict] = []
    seen: set[str] = set()

    def _add(chip: dict) -> None:
        v = str(chip.get("value", ""))
        if v and v not in seen:
            seen.add(v)
            chips.append(chip)

    tail = answer_tail.strip()[-200:] if answer_tail else ""

    # Detect whether the agent admitted it had no KB data for this topic.
    # When true, intent-specific chips would be misleading so we substitute
    # generic navigation chips instead.
    no_kb_data = bool(tail and _NO_KB_DATA_RE.search(tail))

    # 1. Yes/No chips when answer tail ends with a relevant question
    if tail.endswith("?") and _YN_QUESTION_RE.search(tail):
        _add({"label": "Yes, explain more", "value": "Please explain that in more detail"})
        _add({"label": "No, that's all", "value": "No, that's all I need"})

    if no_kb_data:
        # Skip intent chips — offer useful navigation to topics we CAN answer
        for chip in _NO_DATA_FALLBACK_CHIPS:
            _add(chip)
            if len(chips) >= 6:
                break
    else:
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

    # Start KB prefetch immediately — runs in parallel with classify_intent.
    # For the common 4g (RAG) path the embedding + DB query (~400ms–2s) will
    # finish during the 9-11s classification LLM call, so by the time we reach
    # step 4g the result is already available (≈0ms extra wait).
    # All early-return branches (4a–4f) cancel this task before returning.
    kb_task: asyncio.Task = asyncio.create_task(_prefetch_kb(raw_message))

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

    _classify_done_at = time.perf_counter()
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
        kb_task.cancel()
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
        kb_task.cancel()
        return

    # ── 4a. Conversation complete → inline closure, no chips ──────────────
    # Guard: only honour close_conversation when the message actually looks like
    # a sign-off. If the message contains banking keywords or a question mark the
    # classifier hallucinated the action — fall through to the agent loop instead.
    if classification.assistant_action == "close_conversation" and not _is_real_question(raw_message):
        if classification.language == "bn":
            closure = "আপনাকে সহায়তা করতে পেরে ভালো লাগলো! যেকোনো সময় প্রয়োজন হলে নির্দ্বিধায় আমাদের সাথে যোগাযোগ করুন! শুভদিন কাটসুন!"
        elif classification.language == "banglish":
            closure = "Apnake help korte pere valo laglo! Jodi aro kono dorkar hoy, amader sathe jogajog korun. Shubho din!"
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
        kb_task.cancel()
        return

    # ── 4b. Low-confidence disambiguation → ask clarifying question ───────
    # Only catch genuinely ambiguous / low-confidence input here.
    # High-confidence specific banking queries (e.g. "block or replace my card",
    # intent=card_services conf=0.95) should fall through to the agent loop so
    # the main model can answer all aspects of the question intelligently.
    # Threshold: confidence < 0.65 OR no specific intent identified.
    _is_truly_ambiguous = (
        classification.confidence < 0.65
        or classification.intent in ("general_faq",)
    )
    # Never treat "explain more / re-clarification" requests as ambiguous dead-ends —
    # those have is_clarification=True and belong in step 4d (re-explain LLM path).
    # Blocking them here produces hard-coded "are you done?" replies even when the
    # user just asked for elaboration, which also breaks multilingual phrasing.
    if (
        classification.assistant_action == "ask_clarification"
        and _is_truly_ambiguous
        and not classification.is_clarification
    ):
        _uctx = memory.get_user_context()
        _fname = (_uctx.get("username") or "").split()[0] if _uctx.get("username") else ""
        if classification.language == "bn":
            disambig = "ক্ষমাকরুন, আমি নিশ্চিত হতে চাইছি — আপনি কি সারা হয়েছেন, নাকি আরও কোনো সাহায্যের প্রয়োজন আছে?"
        elif classification.language == "banglish":
            disambig = "Just to confirm — apni ki sesh korechhen, naaki aro kono help dorkar?"
        else:
            _name_part = f", {_fname}" if _fname else ""
            disambig = f"Just to confirm{_name_part} — are you all done, or is there something else I can help you with?"

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
        kb_task.cancel()
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
            kb_task.cancel()
            return
        # No active flow to abort — fall through to normal routing
        _log_route(conversation_id, "branch_abort_flow_skipped", reason="no_active_flow")

    # ── 4d. Re-explain / clarification (classifier authority only) ────────
    # Guard: if the classifier marked is_clarification=True but the intent is a
    # specific banking category with high confidence, the user is asking a NEW
    # question on a different topic — not requesting a re-explanation of the
    # last answer.  In that case skip re-explain and fall through to agent loop.
    # Example: "how to open fdr account opening" after a money-transfer answer.
    _clarification_overridden_by_new_topic = (
        classification.is_clarification
        and classification.intent not in ("general_faq", "greeting", "small_talk")
        and classification.confidence >= 0.80
        and _is_real_question(raw_message)
    )
    if _clarification_overridden_by_new_topic:
        logger.info(
            "[%s] clarification_override: new banking question detected "
            "(intent=%s conf=%.2f) — skipping re-explain",
            conversation_id, classification.intent, classification.confidence,
        )
        # Fix up the action so caching + system-prompt downstream treats this as RAG
        classification.assistant_action = "answer_with_rag"
        classification.is_clarification = False
        classification.conversation_act = "normal_banking_query"
    if classification.is_clarification and last_bot and not _clarification_overridden_by_new_topic:
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
        kb_task.cancel()
        return

    # ── 4d2. Greeting/small-talk fast path (no active flow) ───────────────
    # Avoids unnecessary LLM tool loop for pure greetings and language-style
    # small-talk such as "hi", "how are you", "speak in bangla".
    is_small_talk = bool(_SMALL_TALK_ROUTE_RE.search(raw_message))
    if not active_flow_name and classification.intent == "greeting":
        if classification.language == "bn" or re.search(r"বাংলা|bangla|bengali", raw_message, re.IGNORECASE):
            reply = "জি, অবশ্যই। আমি বাংলায় কথা বলতে পারি। আপনি কী বিষয়ে সাহায্য চান?"
        elif classification.language == "banglish":
            reply = "Hi! Apni Banglish-e kotha bolte paren, ami bujhte parbo. Apnar banking bishoe ki jannar ache?"
        elif classification.language == "hinglish":
            reply = "Hi! Main aapki banking mein madad karne ke liye yahan hoon. Kya jaanna chahte hain?"
        else:
            _uctx_g = memory.get_user_context()
            _gname = (_uctx_g.get("username") or "").split()[0] if _uctx_g.get("username") else ""
            reply = (f"Hi, {_gname}! How can I help you with your banking today?" if _gname else "Hi! How can I help you with your banking today?")

        greeting_chips = (classification.suggested_actions or [])[:4]

        memory.add_user_message(raw_message)
        await emit_fn("thinking_end", {})
        await emit_fn("text_delta", {"delta": reply})
        await emit_fn("state", {k: v for k, v in memory.get_state().items() if k != "suggested_actions"})
        await emit_fn("finish", {
            "finishReason": "stop",
            "usage": {"promptTokens": 0, "completionTokens": 0},
            "suggestedActions": greeting_chips,
        })
        memory.add_assistant_message(content=reply)
        _log_route(conversation_id, "finish_small_talk", chips=len(greeting_chips))
        kb_task.cancel()
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
        kb_task.cancel()
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
            memory.replace_state(state_update)
            await emit_fn("state", {k: v for k, v in memory.get_state().items() if k != "suggested_actions"})
            await emit_fn("finish", {"finishReason": "stop", "usage": {"promptTokens": 0, "completionTokens": 0}, "suggestedActions": first_quick_replies or []})
            memory.add_assistant_message(content=intro_text)
            _log_route(conversation_id, "finish_flow_intro", quick_replies=len(first_quick_replies or []))
            kb_task.cancel()
            return

    # ── 4g. KB prefetch + full agent loop ────────────────────────────────
    # kb_task was already created before classify_intent (parallel execution).
    _log_route(conversation_id, "branch_agent_loop", reason="no_flow_or_special_action")

    # ── Response cache check (only for answer_with_rag with high kb_conf) ──
    if classification.assistant_action == "answer_with_rag":
        _ckey = _cache_key(raw_message, classification.intent)
        _cached = _cache_get(_ckey)
        if _cached is not None:
            logger.info("[%s] response_cache HIT key=%s", conversation_id, _ckey[:10])
            kb_task.cancel()
            await emit_fn("thinking_end", {})
            await emit_fn("text_delta", {"delta": _cached["answer"]})
            if _cached["sources"]:
                _cached_visible = [
                    s for s in _cached["sources"]
                    if s.get("document_type") == "procedure" and s.get("is_active", False)
                ]
                if _cached_visible:
                    await emit_fn("sources", {"sources": _cached_visible})
            await emit_fn("finish", {
                "finishReason": "stop",
                "usage": {"promptTokens": 0, "completionTokens": 0},
                "suggestedActions": _cached["chips"],
            })
            return

    handoff_text = str(getattr(classification, "handoff_text", "") or "").strip()
    handoff_text = _sanitize_handoff_text(
        handoff_text,
        _fallback_handoff_text_for_message(raw_message, language=classification.language),
    )
    if handoff_text:
        await emit_fn("thinking_end", {})
        await emit_fn("text_delta", {"delta": handoff_text + " "})
        await emit_fn("thinking_start", {})

    # Progressive status updates while KB fetches + LLM warms up
    _status_stop = asyncio.Event()
    _status_task: asyncio.Task = asyncio.create_task(
        _run_status_loop(
            emit_fn,
            _get_status_steps(classification.intent, classification.language),
            _status_stop,
        )
    )

    async def _push_chips_bg() -> list[dict]:
        chips = _build_chips(classification)
        await emit_fn("chips_update", {"suggestedActions": chips})
        return chips

    chip_task: asyncio.Task = asyncio.create_task(_push_chips_bg())

    kb_wait_started = time.perf_counter()
    try:
        from app.tools.vector_search import embedding_backend_degraded
        degraded_before_prefetch = embedding_backend_degraded()
    except Exception:
        degraded_before_prefetch = False
    prefetch_timeout_ms = (
        settings.kb_prefetch_timeout_ms_degraded
        if degraded_before_prefetch
        else settings.kb_prefetch_timeout_ms
    )
    try:
        kb_context, kb_confidence, kb_sources = await asyncio.wait_for(
            kb_task,
            timeout=max(0.1, prefetch_timeout_ms / 1000.0),
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        kb_context, kb_confidence, kb_sources = "", 0.0, []
        logger.warning("[%s] KB prefetch timed out — LLM will use tools if needed", conversation_id)
    kb_wait_ms = (time.perf_counter() - kb_wait_started) * 1000

    # Language-aware confidence correction: the cross-encoder reranker is
    # English-only. For non-English (Bangla, Banglish, Hinglish) it produces
    # very low scores (~-10) which collapses multi-signal confidence to ~0.30.
    # When language != "en" and we have retrieval results, recalculate
    # confidence using count + keyword signals only (no reranker signal).
    if (
        classification.language in ("bn", "banglish", "hinglish", "other")
        and kb_sources
        and kb_confidence < 0.60
    ):
        _n = len(kb_sources)
        _count_signal = 1.0 if _n >= 2 else 0.5
        _keyword_bonus = 0.15 if _n >= 1 else 0.0
        kb_confidence = min(0.75, 0.60 * _count_signal + _keyword_bonus)
        logger.info(
            "[%s] kb_confidence adjusted for non-English (%s): %.2f (n=%d)",
            conversation_id, classification.language, kb_confidence, _n,
        )

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

    try:
        from app.tools.vector_search import embedding_backend_degraded
        degraded_after_prefetch = embedding_backend_degraded()
    except Exception:
        degraded_after_prefetch = degraded_before_prefetch

    enriched_context = dict(extra_context or {})
    disable_kb_tool = bool(settings.disable_kb_tool_when_embedding_down and degraded_after_prefetch)
    enriched_context.update({
        "_last_topic": current_state.get("_last_topic", ""),
        "_negative_sentiment_count": current_state.get("_negative_sentiment_count", 0),
        "_clarification_count": current_state.get("_clarification_count", 0),
        "_kb_context": kb_context,
        "_kb_confidence": kb_confidence,
        "_kb_sources": kb_sources,
        "_intent": classification.intent,
        "_assistant_action": classification.assistant_action,
        "_conversation_act": classification.conversation_act,
        "_classifier_confidence": classification.confidence,
        "_last_bot_message": last_bot,
        "_preface_text": handoff_text,
        "_disable_kb_tool": disable_kb_tool,
        "_kb_unavailable": disable_kb_tool,
    })
    logger.info(
        "[%s] kb_degraded_state before_prefetch=%s after_prefetch=%s disable_kb_tool=%s",
        conversation_id,
        degraded_before_prefetch,
        degraded_after_prefetch,
        disable_kb_tool,
    )

    if is_first or classification.intent == "greeting":
        current_state["suggested_actions"] = classification.suggested_actions
        memory.update_state(current_state)

    guarded_emit, finalize_guardrail = _make_guardrail_emit(emit_fn, conversation_id)
    try:
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
    finally:
        _status_stop.set()
        _status_task.cancel()
    if not isinstance(usage, dict):
        usage = {"promptTokens": 0, "completionTokens": 0}
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

    # Store in response cache for high-confidence RAG answers
    if (
        classification.assistant_action == "answer_with_rag"
        and kb_confidence >= 0.75
        and last_answer
    ):
        _ckey = _cache_key(raw_message, classification.intent)
        _cache_put(_ckey, last_answer, kb_sources, final_chips)
        logger.debug("[%s] response_cache STORED key=%s", conversation_id, _ckey[:10])

    _total_ms = (time.perf_counter() - route_started) * 1000
    _classify_ms = (_classify_done_at - route_started) * 1000
    _agent_ms = _total_ms - _classify_ms - kb_wait_ms
    logger.info(
        "REQUEST_METRICS conv=%s intent=%s action=%s conf=%.2f "
        "classify_ms=%.0f kb_prefetch_ms=%.0f agent_ms=%.0f total_ms=%.0f "
        "strong_kb=%s kb_conf=%.2f",
        conversation_id,
        classification.intent,
        classification.assistant_action,
        classification.confidence,
        _classify_ms,
        kb_wait_ms,
        _agent_ms,
        _total_ms,
        str(kb_confidence >= 0.75),
        kb_confidence,
    )
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
    memory.replace_state(current_state)
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
        memory.replace_state(state_update)
        await emit_fn("state", {k: v for k, v in memory.get_state().items() if k != "suggested_actions"})
        await emit_fn("finish", {"finishReason": "stop", "usage": {"promptTokens": 0, "completionTokens": 0}, "suggestedActions": abort_chips})
        memory.add_assistant_message(content=result.next_question)
        return

    if result.is_complete and result.completion_context:
        # Capture flow name before it's cleared from session state
        active_flow_name = engine.flow.name

        # ─ Build a KB search query from the flow topic only (not slot values) ────
        def _build_flow_kb_query(fname: str, flow_intent: str | None) -> str:
            """Return a clean topic query for KB lookup — no user slot values."""
            label_map = {
                "download_statement": "how to download bank account statement",
                "fund_transfer": "how to transfer money bank account",
                "account_opening": "how to open a new bank account",
                "card_services": "credit debit card services",
            }
            base = label_map.get(fname, fname.replace("_", " "))
            if flow_intent and flow_intent.replace("_", " ") not in base:
                base = flow_intent.replace("_", " ") + " " + base
            return base.strip()

        completion_text = result.completion_context

        if settings.flow_kb_augment:
            try:
                from app.tools.vector_search import search_banking_knowledge, VectorSearchInput
                from app.agent.core import run_flow_completion_with_emitter

                flow_intent = getattr(engine.flow, "intent", None)
                _fq = _build_flow_kb_query(active_flow_name, flow_intent)
                # Restrict search to chunks tagged with this flow's intent
                # so we get the right document, not generic procedure docs.
                _intent_filter = [active_flow_name]
                if flow_intent and flow_intent != active_flow_name:
                    _intent_filter.append(flow_intent)
                _kb_raw = await search_banking_knowledge(
                    VectorSearchInput(
                        query=_fq,
                        top_k=3,
                        intent_tags=_intent_filter,
                    )
                )
                _kb_ctx, _kb_conf, _kb_sources = _extract_kb_prefetch_payload(_kb_raw)

                # Fall back to broad search if intent-filtered search returns nothing
                if not _kb_ctx:
                    _kb_raw = await search_banking_knowledge(VectorSearchInput(query=_fq, top_k=3))
                    _kb_ctx, _kb_conf, _kb_sources = _extract_kb_prefetch_payload(_kb_raw)

                if _kb_ctx:
                    logger.info(
                        "[%s] flow_completion: KB-augment active (conf=%.2f sources=%d query=%r)",
                        conversation_id, _kb_conf, len(_kb_sources), _fq[:80],
                    )
                    # Show only the single best-matching source (highest reranker_score)
                    # from procedure+active docs, deduped by title. This avoids showing
                    # unrelated chunks that happen to share the same document_type.
                    _proc_sources = _visible_sources(_kb_sources)
                    if _proc_sources:
                        # Sort by reranker_score descending, take best per unique title
                        _proc_sources.sort(key=lambda s: s.get("reranker_score", 0.0), reverse=True)
                        _seen_titles: set[str] = set()
                        _flow_sources = []
                        for _s in _proc_sources:
                            _t = _s.get("document_title", "")
                            if _t not in _seen_titles:
                                _seen_titles.add(_t)
                                _flow_sources.append(_s)
                                if len(_flow_sources) >= 1:  # only the top source
                                    break
                        if _flow_sources:
                            await emit_fn("sources", {"sources": _flow_sources})

                    completion_text = await run_flow_completion_with_emitter(
                        flow_name=active_flow_name,
                        collected_slots=result.collected_slots,
                        kb_context=_kb_ctx,
                        fallback_text=result.completion_context,
                        conversation_id=conversation_id,
                        memory=memory,
                        emit_fn=emit_fn,
                        bank_name=settings.bank_name,
                    )
                else:
                    logger.info(
                        "[%s] flow_completion: no KB results — using template",
                        conversation_id,
                    )
                    await emit_fn("text_delta", {"delta": completion_text})
            except Exception as _fkb_exc:
                logger.warning("[%s] flow KB augment failed: %s — using template", conversation_id, _fkb_exc)
                await emit_fn("text_delta", {"delta": completion_text})
        else:
            await emit_fn("text_delta", {"delta": completion_text})

        state_update = memory.get_state()
        state_update.pop("suggested_actions", None)
        memory.replace_state(state_update)
        await emit_fn("state", {k: v for k, v in memory.get_state().items() if k != "suggested_actions"})
        await emit_fn("finish", {"finishReason": "stop", "usage": {"promptTokens": 0, "completionTokens": 0}, "suggestedActions": []})
        memory.add_assistant_message(content=completion_text)
        return

    # Next flow step — emit question + quick replies
    if result.next_question:
        await emit_fn("text_delta", {"delta": result.next_question})
        state_update = memory.get_state()
        state_update.pop("suggested_actions", None)
        memory.replace_state(state_update)
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

