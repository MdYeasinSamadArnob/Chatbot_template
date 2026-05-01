"""
Intent classification and clarification detection.

Provides:
  - detect_clarification()     — fast regex, no LLM needed
  - detect_abort()             — fast regex, no LLM needed
  - detect_negative_sentiment() — fast regex, no LLM needed
  - classify_intent()          — single non-streaming LLM call (no tools, 1 iteration)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import hashlib
from dataclasses import dataclass, field
from typing import Optional
from collections import OrderedDict

from app.agent.intent_taxonomy import FALLBACK_INTENT, INTENTS, IntentDefinition
from app.config import settings

logger = logging.getLogger(__name__)


# ── Classifier cache (in-process, bounded LRU + TTL) ─────────────────────

_CLASSIFIER_CACHE: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()


def _context_signature(
    conversation_history: list[dict],
    last_bot_message: str,
    active_flow_name: str | None,
    last_topic: str,
) -> str:
    recent = [
        (m.get("role", ""), (m.get("content") or "")[:120])
        for m in conversation_history
        if m.get("role") in ("user", "assistant") and m.get("content")
    ][-2:]
    raw = json.dumps(
        {
            "recent": recent,
            "last_bot": (last_bot_message or "")[:120],
            "flow": active_flow_name or "",
            "topic": last_topic or "",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _classifier_cache_key(
    message: str,
    conversation_history: list[dict],
    last_bot_message: str,
    active_flow_name: str | None,
    last_topic: str,
) -> str:
    normalized = " ".join((message or "").strip().lower().split())
    return f"{normalized}|{_context_signature(conversation_history, last_bot_message, active_flow_name, last_topic)}"


def _cache_get(key: str) -> dict | None:
    cached = _CLASSIFIER_CACHE.get(key)
    if not cached:
        return None
    expires_at, payload = cached
    if time.monotonic() >= expires_at:
        _CLASSIFIER_CACHE.pop(key, None)
        return None
    _CLASSIFIER_CACHE.move_to_end(key)
    return payload


def _cache_set(key: str, payload: dict) -> None:
    ttl = max(1, int(settings.classifier_cache_ttl_seconds))
    _CLASSIFIER_CACHE[key] = (time.monotonic() + ttl, payload)
    _CLASSIFIER_CACHE.move_to_end(key)
    max_entries = max(32, int(settings.classifier_cache_max_entries))
    while len(_CLASSIFIER_CACHE) > max_entries:
        _CLASSIFIER_CACHE.popitem(last=False)


# ── Regex patterns ─────────────────────────────────────────────────────────

_CLARIFICATION_RE = re.compile(
    r"\b(don['']?t\s+understand|didn['']?t\s+understand|don'?t\s+get\s+it|"
    r"didn'?t\s+get\s+it|can'?t\s+understand|confused|unclear|"
    r"what\s+do\s+you\s+mean|elaborate|can\s+you\s+explain|explain\s+again|"
    r"explain\s+more|simplify|can\s+you\s+simplify|clarify|please\s+clarify|"
    r"say\s+that\s+again|tell\s+me\s+again|more\s+detail|in\s+simpler|"
    r"simpler\s+terms|not\s+clear|বুঝলাম\s+না|বুঝিনি|আবার\s+বলুন|"
    r"সহজ\s+করে|বুঝিয়ে\s+দিন|বুঝতে\s+পারছি\s+না)\b",
    re.IGNORECASE,
)

_SHORT_PRONOUN_RE = re.compile(
    r"^[\w\s''?!.,]*\b(it|this|that|these|those|step|above|the\s+last|"
    r"the\s+previous|what\s+you\s+said|which\s+one|how)\b[\w\s''?!.,]*$",
    re.IGNORECASE,
)

_ABORT_RE = re.compile(
    r"\b(cancel|stop|abort|never\s+mind|nevermind|forget\s+it|quit|exit|"
    r"go\s+back|start\s+over|not\s+now|no\s+thanks|বাতিল|থামুন|না\s+থাক|"
    r"ছেড়ে\s+দিন|বন্ধ\s+করুন)\b",
    re.IGNORECASE,
)

_NEGATIVE_SENTIMENT_RE = re.compile(
    r"\b(useless|terrible|awful|worst|hate|frustrat|angry|upset|"
    r"waiting|waited|waiting\s+for|wrong\s+charge|not\s+working|broken|"
    r"ridiculous|unacceptable|waste\s+of\s+time|no\s+help|useless\s+bot|"
    r"doesn'?t\s+work|isn'?t\s+working|poor\s+service|"
    r"বিরক্ত|রাগ|সমস্যা|কাজ\s+করছে\s+না|অকেজো|বাজে)\b",
    re.IGNORECASE,
)

_GREETING_RE = re.compile(
    r"^(hi|hello|hey|হ্যালো|হ্যাই|সালাম|আস্সালামু|good\s*(morning|afternoon|evening|day))"
    r"[!\s.،،،]*$",
    re.IGNORECASE,
)

# Friendly small-talk that should NOT be treated as clarification.
_SMALL_TALK_RE = re.compile(
    r"\b(how\s+are\s+you|kemon\s+acho|kemon\s+asen|"
    r"speak\s+in\s+bangla|speak\s+bangla|banglay\s+kotha|"
    r"can\s+you\s+speak\s+(bangla|bengali)|"
    r"amar\s+sathe\s+bangla(te)?\s+kotha\s+bolo)\b",
    re.IGNORECASE,
)

# "how to/do/can X" patterns are new banking questions, not clarifications.
_HOW_NEW_QUESTION_RE = re.compile(
    r"^how\s+(to|do|can|would|should|could|is|are|does)\b",
    re.IGNORECASE,
)

_AFFIRMATIVE_SHORT_RE = re.compile(
    r"^\s*(yes|yes\s+please|yeah|yep|sure|okay|ok|continue|go\s+ahead|হ্যাঁ|জি|ঠিক\s+আছে|acha|haan)\s*[.!]*\s*$",
    re.IGNORECASE,
)


def _default_handoff_text(
    assistant_action: str,
    intent_name: str,
    language: str,
) -> str:
    """Short bridge text streamed while the main answer is still being prepared."""
    import random

    if language == "bn":
        if assistant_action == "re_explain":
            return random.choice([
                "আমি সহজ করে আবার বুঝিয়ে দিচ্ছি।",
                "চলুন আরেকটু সহজভাবে বলি।",
                "আবার একটু পরিষ্কার করে বলছি।",
            ])
        if assistant_action == "escalate":
            return "আমি এখনই আপনাকে সাপোর্ট এজেন্টের সাথে যুক্ত করছি।"
        _BN_POOLS: dict[str, list[str]] = {
            "fund_transfer": [
                "ট্রান্সফারের সঠিক ধাপগুলো দেখে নিচ্ছি।",
                "ট্রান্সফার পদ্ধতি খুঁজে দিচ্ছি।",
                "সেরা ট্রান্সফার অপশনটি দেখছি।",
            ],
            "card_services": [
                "কার্ড সংক্রান্ত তথ্য দেখছি।",
                "কার্ডের ধাপগুলো খুঁজে নিচ্ছি।",
            ],
            "account_inquiry": [
                "অ্যাকাউন্টের তথ্য দেখছি।",
                "অ্যাকাউন্ট সংক্রান্ত বিস্তারিত খুঁজছি।",
            ],
            "loan_services": [
                "ঋণ সংক্রান্ত তথ্য দেখছি।",
                "লোনের বিস্তারিত খুঁজছি।",
            ],
        }
        pool = _BN_POOLS.get(intent_name)
        if pool:
            return random.choice(pool)
        return random.choice([
            "আপনার জন্য সঠিক তথ্যটি দেখে নিচ্ছি।",
            "এক মুহূর্ত — তথ্য খুঁজছি।",
            "আপনার প্রশ্নের উত্তর খুঁজছি।",
        ])

    if assistant_action == "re_explain":
        return random.choice([
            "Let me explain that more clearly.",
            "Let me try that again with a simpler explanation.",
            "Sure, let me break that down differently.",
        ])
    if assistant_action == "escalate":
        return "Connecting you with a support agent now."

    _EN_POOLS: dict[str, list[str]] = {
        "fund_transfer": [
            "Let me find the right transfer steps for you.",
            "Checking the transfer options for your request.",
            "Looking up the transfer details now.",
        ],
        "card_services": [
            "Looking up the card-related steps for you.",
            "Checking card information — just a moment.",
            "Let me find the right card details.",
        ],
        "account_inquiry": [
            "Pulling the account details you need.",
            "Let me check that account information.",
            "Looking up your account info now.",
        ],
        "loan_services": [
            "Checking the loan details for you.",
            "Looking up loan information now.",
            "Let me find the relevant loan details.",
        ],
    }
    pool = _EN_POOLS.get(intent_name)
    if pool:
        return random.choice(pool)
    return random.choice([
        "Let me find the right information for you.",
        "Checking the details for your request.",
        "Looking that up for you now.",
        "One moment while I check that for you.",
    ])

# ── Mapping: assistant_action → reply_style ──────────────────────────────

_REPLY_STYLE_MAP: dict[str, str] = {
    "close_conversation": "brief_closure",
    "abort_flow": "confirmation",
    "ask_clarification": "confirmation",
    "re_explain": "re_explain",
    "answer_with_rag": "rag_answer",
    "offer_alternatives": "rag_answer",
    "escalate": "escalate",
    "resume_flow": "continue_flow",
    "continue_flow": "continue_flow",
}

_VALID_CONVERSATION_ACTS = frozenset({
    "normal_banking_query",
    "conversation_complete",
    "flow_abort",
    "decline_current_suggestion",
    "decline_escalation",
    "acknowledgement_only",
    "clarification_request",
    "complaint_or_frustration",
})

_VALID_ASSISTANT_ACTIONS = frozenset({
    "close_conversation",
    "abort_flow",
    "resume_flow",
    "continue_flow",
    "re_explain",
    "answer_with_rag",
    "offer_alternatives",
    "escalate",
    "ask_clarification",
})


def _parse_classifier_structured_output(raw: str) -> dict[str, object] | None:
    """
    Accept either JSON or a compact tagged block.

    Tagged format example:
    INTENT: money_transfer
    CONFIDENCE: 0.92
    ACT: normal_banking_query
    ACTION: answer_with_rag
    LANGUAGE: en
    SENTIMENT: neutral
    HANDOFF_TEXT: I’m checking the transfer details for you.
    NEXT_LIKELY: check_balance|account_services
    """
    raw = (raw or "").strip()
    if not raw:
        return None

    json_match = re.search(r"\{[\s\S]*\}", raw)
    if json_match:
        try:
            data = json.loads(json_match.group())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    fields: dict[str, str] = {}
    for line in raw.splitlines():
        match = re.match(r"^\s*([A-Z_]+)\s*:\s*(.*?)\s*$", line)
        if not match:
            continue
        key, value = match.groups()
        fields[key] = value

    if not fields:
        return None

    next_likely_raw = fields.get("NEXT_LIKELY", "")
    next_likely = [
        item.strip()
        for item in re.split(r"[|,]", next_likely_raw)
        if item.strip()
    ]

    parsed: dict[str, object] = {
        "intent": fields.get("INTENT", ""),
        "confidence": fields.get("CONFIDENCE", "0.5"),
        "conversation_act": fields.get("ACT", fields.get("CONVERSATION_ACT", "")),
        "assistant_action": fields.get("ACTION", fields.get("ASSISTANT_ACTION", "")),
        "language": fields.get("LANGUAGE", ""),
        "sentiment": fields.get("SENTIMENT", ""),
        "handoff_text": fields.get("HANDOFF_TEXT", ""),
        "next_likely": next_likely,
    }
    return parsed


# ── Result dataclass ───────────────────────────────────────────────────────

@dataclass
class ClassificationResult:
    intent: str
    confidence: float
    # Conversation-act fields (new)
    conversation_act: str       # e.g. conversation_complete, flow_abort, …
    assistant_action: str       # single routing authority field
    language: str               # en | bn | hinglish | other
    sentiment: str              # positive | neutral | negative
    reply_style: str            # derived from assistant_action
    should_end_conversation: bool
    should_abort_flow: bool
    # Legacy compatibility fields
    is_clarification: bool
    is_abort: bool
    is_negative_sentiment: bool
    suggested_profile: str
    flow_name: Optional[str]
    required_slots: list[str]
    handoff_text: str = ""
    suggested_actions: list[dict] = field(default_factory=list)
    next_likely: list[str] = field(default_factory=list)


# ── Fast detectors (no LLM) ────────────────────────────────────────────────

def detect_clarification(message: str, last_bot_message: str) -> bool:
    """Detect re-explanation requests without an LLM call."""
    msg = message.strip()

    # Greeting/small-talk should never be interpreted as clarification.
    if _GREETING_RE.match(msg) or _SMALL_TALK_RE.search(msg):
        return False

    if _CLARIFICATION_RE.search(msg):
        return True

    # Very short message (≤6 words) referencing pronouns when there is prior context.
    # Guard: "how to/do/can/would X" patterns are new questions, never clarifications.
    if last_bot_message and len(msg.split()) <= 6 and _SHORT_PRONOUN_RE.match(msg):
        if not _HOW_NEW_QUESTION_RE.match(msg):
            return True

    # Single-word question like "huh?" "what?" with prior context
    if last_bot_message and len(msg.split()) <= 2 and msg.endswith("?"):
        return True

    return False


def detect_abort(message: str) -> bool:
    """Detect flow-cancellation intent without an LLM call."""
    return bool(_ABORT_RE.search(message))


def detect_negative_sentiment(message: str) -> bool:
    """Detect frustrated or angry tone without an LLM call."""
    return bool(_NEGATIVE_SENTIMENT_RE.search(message))


async def classify_intent(
    message: str,
    conversation_history: list[dict],
    is_first_message: bool = False,
    last_bot_message: str = "",
    active_flow_name: str | None = None,
    last_topic: str = "",
) -> ClassificationResult:
    """
    Classify the user's intent AND conversation act using a single LLM pass.

    Returns a rich ClassificationResult with:
      - intent: which banking domain the user is asking about
      - conversation_act: what the user is *doing* conversationally
      - assistant_action: single authority field driving routing decisions
      - language, sentiment, reply_style, confidence, next_likely

    Confidence fallback: if confidence < 0.75 and assistant_action is
    terminal (close_conversation, abort_flow), overrides to ask_clarification
    to avoid silently ending or aborting on ambiguous input.
    """
    msg = message.strip()
    cache_key = _classifier_cache_key(
        message=msg,
        conversation_history=conversation_history,
        last_bot_message=last_bot_message,
        active_flow_name=active_flow_name,
        last_topic=last_topic,
    )
    cached = _cache_get(cache_key)
    if cached:
        intent_name = str(cached.get("intent", "general_faq"))
        intent_def = INTENTS.get(intent_name, FALLBACK_INTENT)
        return ClassificationResult(
            intent=intent_name,
            confidence=float(cached.get("confidence", 0.7)),
            conversation_act=str(cached.get("conversation_act", "normal_banking_query")),
            assistant_action=str(cached.get("assistant_action", "answer_with_rag")),
            language=str(cached.get("language", "en")),
            sentiment=str(cached.get("sentiment", "neutral")),
            reply_style=str(cached.get("reply_style", "rag_answer")),
            should_end_conversation=bool(cached.get("should_end_conversation", False)),
            should_abort_flow=bool(cached.get("should_abort_flow", False)),
            is_clarification=bool(cached.get("is_clarification", False)),
            is_abort=bool(cached.get("is_abort", False)),
            is_negative_sentiment=bool(cached.get("is_negative_sentiment", False)),
            suggested_profile=intent_def.profile,
            flow_name=intent_def.flow_name,
            required_slots=intent_def.required_slots,
            handoff_text=str(cached.get("handoff_text", "")),
            suggested_actions=intent_def.suggested_actions,
            next_likely=list(cached.get("next_likely", []))[:2],
        )
    if logger.isEnabledFor(logging.INFO):
        logger.info(
            "[classifier] start | msg=%r | is_first=%s | active_flow=%s | has_last_bot=%s",
            msg[:140],
            is_first_message,
            active_flow_name or "none",
            bool(last_bot_message),
        )

    if is_first_message and _GREETING_RE.match(msg):
        intent_def = INTENTS["greeting"]
        return ClassificationResult(
            intent="greeting",
            confidence=1.0,
            conversation_act="normal_banking_query",
            assistant_action="continue_flow",
            language="en",
            sentiment="positive",
            reply_style="rag_answer",
            should_end_conversation=False,
            should_abort_flow=False,
            is_clarification=False,
            is_abort=False,
            is_negative_sentiment=False,
            suggested_profile=intent_def.profile,
            flow_name=intent_def.flow_name,
            required_slots=intent_def.required_slots,
            handoff_text="",
            suggested_actions=intent_def.suggested_actions,
        )

    # Deterministic non-first-turn greeting/small-talk handling.
    # Prevents expensive misroutes where "hi/how are you" is treated as
    # clarification and triggers irrelevant RAG/tool calls.
    if _GREETING_RE.match(msg) or _SMALL_TALK_RE.search(msg):
        intent_def = INTENTS["greeting"]
        return ClassificationResult(
            intent="greeting",
            confidence=0.95,
            conversation_act="acknowledgement_only",
            assistant_action="continue_flow",
            language="bn" if re.search(r"বাংলা|bangla|bengali", msg, re.IGNORECASE) else "en",
            sentiment="positive",
            reply_style="rag_answer",
            should_end_conversation=False,
            should_abort_flow=False,
            is_clarification=False,
            is_abort=False,
            is_negative_sentiment=False,
            suggested_profile=intent_def.profile,
            flow_name=intent_def.flow_name,
            required_slots=intent_def.required_slots,
            handoff_text="",
            suggested_actions=intent_def.suggested_actions,
            next_likely=[],
        )

    intent_list_lines = "\n".join(
        f"{name}: {defn.description}"
        for name, defn in INTENTS.items()
    )

    recent_turns: list[str] = []
    eligible = [
        m for m in conversation_history
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    for m in eligible[-2:]:
        role = m["role"].upper()
        content = (m.get("content") or "")[:120]
        recent_turns.append(f"{role}: {content}")
    recent_ctx = "\n".join(recent_turns) if recent_turns else "(no prior context)"

    active_flow_ctx = f'"{active_flow_name}"' if active_flow_name else "none"
    last_bot_ctx = f'"{last_bot_message[:300]}"' if last_bot_message else "none"

    # Optional regex clarification hint (non-authoritative — passed to LLM as context only)
    clarification_detected = detect_clarification(msg, last_bot_message)
    clarification_hint = ""
    if clarification_detected:
        clarification_hint = "\n[Hint: regex detected a possible clarification signal — verify with conversational context]"
        logger.info("[classifier] clarification_regex_hint=true")

    system_prompt = (
        "You are an intent and conversation-act classifier for a banking chatbot.\n"
        "Return ONLY structured output with no explanation and no markdown fences.\n"
        "Use the tagged format below.\n\n"
        "INTENTS:\n"
        f"{intent_list_lines}\n\n"
        "CONVERSATION_ACTS:\n"
        "normal_banking_query, conversation_complete, flow_abort, decline_current_suggestion, "
        "decline_escalation, acknowledgement_only, clarification_request, complaint_or_frustration\n\n"
        "ASSISTANT_ACTIONS:\n"
        "close_conversation, abort_flow, resume_flow, continue_flow, re_explain, "
        "answer_with_rag, offer_alternatives, escalate, ask_clarification\n\n"
        "CRITICAL RULE — close_conversation:\n"
        "Use ACTION: close_conversation ONLY when the message is a pure farewell with "
        "absolutely NO question, topic, or request for information (e.g. 'thanks', 'bye', "
        "'that is all'). If the message contains ANY topic word, question, or intent to "
        "learn something — no matter how brief — use answer_with_rag instead.\n\n"
        "OUTPUT:\n"
        "INTENT: <name from available intents>\n"
        "CONFIDENCE: <0.0-1.0>\n"
        "ACT: <conversation act>\n"
        "ACTION: <assistant action>\n"
        "LANGUAGE: <en|bn|hinglish|other>\n"
        "SENTIMENT: <positive|neutral|negative>\n"
        "NEXT_LIKELY: <intent_a>|<intent_b>\n\n"
        "Leave NEXT_LIKELY empty if none.\n"
        "Do not return any text before or after the structured output."
    )
    user_prompt = (
        f"Active flow: {active_flow_ctx}\n"
        f"Last topic from session memory: {last_topic or 'unknown'}\n"
        f"Last assistant message: {last_bot_ctx}\n\n"
        f"Recent conversation:\n{recent_ctx}\n\n"
        f"Classify this message: {msg}{clarification_hint}"
    )

    intent_name = "general_faq"
    confidence = 0.5
    conversation_act = "normal_banking_query"
    assistant_action = "answer_with_rag"
    language = "en"
    sentiment = "neutral"
    handoff_text = ""
    next_likely: list[str] = []

    try:
        from litellm import acompletion
        from app.config import settings

        model = settings.classifier_model or settings.model_name
        kwargs: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "stream": False,
            "max_tokens": 96,
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
        timeout_seconds = max(0.5, float(settings.classifier_timeout_ms) / 1000.0)
        kwargs["timeout"] = timeout_seconds

        llm_start = time.perf_counter()
        response = await acompletion(**kwargs)
        llm_elapsed_ms = (time.perf_counter() - llm_start) * 1000
        raw = (response.choices[0].message.content or "").strip()
        logger.info(
            "Intent classifier completed in %.0f ms using model=%s",
            llm_elapsed_ms,
            kwargs["model"],
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("[classifier] raw_output=%r", raw[:500])

        data = _parse_classifier_structured_output(raw)
        if data:
            intent_name = str(data.get("intent", "general_faq"))
            confidence = float(data.get("confidence", 0.7))
            if intent_name not in INTENTS:
                intent_name = "general_faq"
                confidence = 0.4
            raw_conv_act = str(data.get("conversation_act", "normal_banking_query"))
            conversation_act = raw_conv_act if raw_conv_act in _VALID_CONVERSATION_ACTS else "normal_banking_query"
            raw_action = str(data.get("assistant_action", "answer_with_rag"))
            assistant_action = raw_action if raw_action in _VALID_ASSISTANT_ACTIONS else "answer_with_rag"
            language = str(data.get("language", "en"))
            sentiment = str(data.get("sentiment", "neutral"))
            raw_handoff_text = data.get("handoff_text", "")
            handoff_text = raw_handoff_text.strip() if isinstance(raw_handoff_text, str) else ""
            raw_next = data.get("next_likely", [])
            next_likely = [
                n for n in (raw_next if isinstance(raw_next, list) else [])
                if isinstance(n, str) and n in INTENTS
            ][:2]
        else:
            logger.warning("[classifier] unparseable_output | raw=%r", raw[:180])

    except asyncio.TimeoutError:
        logger.warning(
            "Intent classification timed out after %sms — defaulting to general_faq",
            settings.classifier_timeout_ms,
        )
    except Exception as exc:
        logger.warning(
            "Intent classification LLM call failed: %s — defaulting to general_faq",
            exc,
        )

    if clarification_detected and assistant_action == "answer_with_rag":
        conversation_act = "clarification_request"
        assistant_action = "re_explain"
        confidence = max(confidence, 0.7)
        logger.info("[classifier] clarification_deterministic_fallback=true | action=re_explain")

    # Guard against malformed first-turn outputs where the model marks a brand-new
    # banking question as a clarification request with no prior context.
    # When prior context exists, trust the LLM's classification — it understands
    # any language/dialect (Banglish, Bengali, Arabic, etc.) better than regex.
    if conversation_act == "clarification_request" and assistant_action != "re_explain":
        if not last_bot_message:
            conversation_act = "normal_banking_query"
            logger.info("[classifier] clarification_act_normalized=true | reason=no_last_bot")

    # Confidence fallback: never silently end or abort on low-confidence signals
    if confidence < 0.75 and assistant_action in ("close_conversation", "abort_flow"):
        logger.info(
            "[classifier] confidence=%.2f below threshold for terminal action=%s — falling back to ask_clarification",
            confidence,
            assistant_action,
        )
        assistant_action = "ask_clarification"

    # Derive convenience booleans
    # Context-direction safeguard: short affirmatives should continue prior direction,
    # not unexpectedly escalate or offer alternatives.
    if _AFFIRMATIVE_SHORT_RE.match(msg) and last_bot_message:
        if assistant_action in ("offer_alternatives", "escalate"):
            assistant_action = "continue_flow"
            conversation_act = "acknowledgement_only"
            if last_topic in INTENTS:
                intent_name = last_topic
            logger.info(
                "[classifier] short_affirmation_override=true | action=continue_flow | intent=%s",
                intent_name,
            )

    should_end_conversation = conversation_act == "conversation_complete" and assistant_action == "close_conversation"
    should_abort_flow = conversation_act == "flow_abort" and assistant_action == "abort_flow"
    is_clarification = conversation_act == "clarification_request" or assistant_action == "re_explain"
    reply_style = _REPLY_STYLE_MAP.get(assistant_action, "rag_answer")
    handoff_text = handoff_text or _default_handoff_text(assistant_action, intent_name, language)

    intent_def = INTENTS.get(intent_name, FALLBACK_INTENT)
    is_negative = detect_negative_sentiment(message)

    logger.debug(
        "[classifier] intent=%s act=%s action=%s conf=%.2f lang=%s",
        intent_name, conversation_act, assistant_action, confidence, language,
    )
    logger.info(
        "[classifier] final | intent=%s | act=%s | action=%s | conf=%.2f | lang=%s | sentiment=%s | clarify=%s | end=%s | abort=%s",
        intent_name,
        conversation_act,
        assistant_action,
        confidence,
        language,
        sentiment,
        is_clarification,
        should_end_conversation,
        should_abort_flow,
    )

    result = ClassificationResult(
        intent=intent_name,
        confidence=confidence,
        conversation_act=conversation_act,
        assistant_action=assistant_action,
        language=language,
        sentiment=sentiment,
        reply_style=reply_style,
        should_end_conversation=should_end_conversation,
        should_abort_flow=should_abort_flow,
        is_clarification=is_clarification,
        is_abort=should_abort_flow,
        is_negative_sentiment=is_negative,
        suggested_profile=intent_def.profile,
        flow_name=intent_def.flow_name,
        required_slots=intent_def.required_slots,
        handoff_text=handoff_text,
        suggested_actions=intent_def.suggested_actions,
        next_likely=next_likely,
    )
    _cache_set(
        cache_key,
        {
            "intent": result.intent,
            "confidence": result.confidence,
            "conversation_act": result.conversation_act,
            "assistant_action": result.assistant_action,
            "language": result.language,
            "sentiment": result.sentiment,
            "reply_style": result.reply_style,
            "should_end_conversation": result.should_end_conversation,
            "should_abort_flow": result.should_abort_flow,
            "is_clarification": result.is_clarification,
            "is_abort": result.is_abort,
            "is_negative_sentiment": result.is_negative_sentiment,
            "handoff_text": result.handoff_text,
            "next_likely": result.next_likely,
        },
    )
    return result
