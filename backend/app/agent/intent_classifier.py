"""
Intent classification and clarification detection.

Provides:
  - detect_clarification()     — fast regex, no LLM needed
  - detect_abort()             — fast regex, no LLM needed
  - detect_negative_sentiment() — fast regex, no LLM needed
  - classify_intent()          — single non-streaming LLM call (no tools, 1 iteration)
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from app.agent.intent_taxonomy import FALLBACK_INTENT, INTENTS, IntentDefinition

logger = logging.getLogger(__name__)


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

_AFFIRMATIVE_SHORT_RE = re.compile(
    r"^\s*(yes|yes\s+please|yeah|yep|sure|okay|ok|continue|go\s+ahead|হ্যাঁ|জি|ঠিক\s+আছে|acha|haan)\s*[.!]*\s*$",
    re.IGNORECASE,
)


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
    suggested_actions: list[dict] = field(default_factory=list)
    next_likely: list[str] = field(default_factory=list)


# ── Fast detectors (no LLM) ────────────────────────────────────────────────

def detect_clarification(message: str, last_bot_message: str) -> bool:
    """Detect re-explanation requests without an LLM call."""
    msg = message.strip()

    if _CLARIFICATION_RE.search(msg):
        return True

    # Very short message (≤6 words) referencing pronouns when there is prior context
    if last_bot_message and len(msg.split()) <= 6 and _SHORT_PRONOUN_RE.match(msg):
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
            suggested_actions=intent_def.suggested_actions,
        )

    intent_list_lines = "\n".join(
        f'- "{name}": {defn.description}'
        for name, defn in INTENTS.items()
    )

    recent_turns: list[str] = []
    eligible = [
        m for m in conversation_history
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    for m in eligible[-4:]:
        role = m["role"].upper()
        content = (m.get("content") or "")[:200]
        recent_turns.append(f"{role}: {content}")
    recent_ctx = "\n".join(recent_turns) if recent_turns else "(no prior context)"

    active_flow_ctx = f'"{active_flow_name}"' if active_flow_name else "none"
    last_bot_ctx = f'"{last_bot_message[:300]}"' if last_bot_message else "none"

    # Optional regex clarification hint (non-authoritative — passed to LLM as context only)
    clarification_hint = ""
    if detect_clarification(msg, last_bot_message):
        clarification_hint = "\n[Hint: regex detected a possible clarification signal — verify with conversational context]"
        logger.info("[classifier] clarification_regex_hint=true")

    system_prompt = (
        "You are an intent and conversation-act classifier for a banking chatbot.\n"
        "Respond ONLY with valid JSON — no explanation, no markdown fences.\n\n"
        f"## Available intents\n{intent_list_lines}\n\n"
        "## Conversation acts\n"
        '- "normal_banking_query": User is asking a new or ongoing banking question.\n'
        '- "conversation_complete": User signals satisfaction, is done, or has no more questions.\n'
        '  Examples: "no that\'s all", "thanks bye", "ok I\'m done", "ধন্যবাদ আর লাগবে না", "thik ache done", "okay thanks"\n'
        '- "flow_abort": User wants to cancel the current in-progress task or flow.\n'
        '  Examples: "cancel", "never mind", "বাতিল করুন", "stop this", "forget it", "শুরু থেকে করি"\n'
        '- "decline_current_suggestion": User declines the latest suggestion but still needs help.\n'
        '  Examples: "no not that", "something else", "I don\'t want that option"\n'
        '- "decline_escalation": User declines being connected to a human agent.\n'
        '  Examples: "no agent", "no thanks I\'m fine here", "I\'ll manage"\n'
        '- "acknowledgement_only": User just acknowledges, no new question.\n'
        '  Examples: "ok", "I see", "got it", "ঠিক আছে", "acha"\n'
        '- "clarification_request": User asks to re-explain or did not understand.\n'
        '  Examples: "didn\'t understand", "what do you mean", "বুঝলাম না", "explain again", "simpler please"\n'
        '- "complaint_or_frustration": User expresses anger, frustration, or dissatisfaction.\n'
        '  Examples: "this is useless", "terrible service", "বিরক্ত হলাম", "not working again"\n\n'
        "## assistant_action values (pick ONE)\n"
        '- "close_conversation": user is satisfied/done — only when conversation_act is conversation_complete\n'
        '- "abort_flow": user wants to cancel active task — only when conversation_act is flow_abort\n'
        '- "re_explain": user wants clarification/simpler explanation\n'
        '- "answer_with_rag": normal banking query needing knowledge lookup\n'
        '- "offer_alternatives": user declined a suggestion but still needs help\n'
        '- "escalate": user wants a human agent\n'
        '- "resume_flow": continue active flow with this user input\n'
        '- "continue_flow": continue normal conversation (no active flow, no specific act)\n\n'
        "## Output format (JSON only)\n"
        '{"intent": "<name from available intents>", "confidence": <0.0-1.0>, '
        '"conversation_act": "<act>", "assistant_action": "<action>", '
        '"language": "<en|bn|hinglish|other>", "sentiment": "<positive|neutral|negative>", '
        '"next_likely": ["<intent_a>", "<intent_b>"]}\n'
        'next_likely: 1-2 intent names the user is most likely to ask about next (exact names from the list; empty list if none).'
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

        json_match = re.search(r"\{[^{}]+\}", raw, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
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
            raw_next = data.get("next_likely", [])
            next_likely = [
                n for n in (raw_next if isinstance(raw_next, list) else [])
                if isinstance(n, str) and n in INTENTS
            ][:2]
        else:
            logger.warning("[classifier] non_json_output | raw=%r", raw[:180])

    except Exception as exc:
        logger.warning(
            "Intent classification LLM call failed: %s — defaulting to general_faq",
            exc,
        )

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

    return ClassificationResult(
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
        suggested_actions=intent_def.suggested_actions,
        next_likely=next_likely,
    )
