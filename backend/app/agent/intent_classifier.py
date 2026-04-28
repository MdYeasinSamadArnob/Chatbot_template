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


# ── Result dataclass ───────────────────────────────────────────────────────

@dataclass
class ClassificationResult:
    intent: str
    confidence: float
    is_clarification: bool
    is_abort: bool
    is_negative_sentiment: bool
    suggested_profile: str
    flow_name: Optional[str]
    required_slots: list[str]
    suggested_actions: list[dict] = field(default_factory=list)


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


# ── LLM-based classifier ───────────────────────────────────────────────────

async def classify_intent(
    message: str,
    conversation_history: list[dict],
    is_first_message: bool = False,
) -> ClassificationResult:
    """
    Classify the user's intent using a fast LLM pass.

    - No tools, temperature=0, single shot.
    - Falls back to 'general_faq' on any LLM or parse error.
    - Greetings are detected by regex to avoid LLM latency.
    """
    msg = message.strip()

    # ── Fast path: greeting detection ─────────────────────────────────
    if is_first_message and _GREETING_RE.match(msg):
        intent_def = INTENTS["greeting"]
        return ClassificationResult(
            intent="greeting",
            confidence=1.0,
            is_clarification=False,
            is_abort=False,
            is_negative_sentiment=False,
            suggested_profile=intent_def.profile,
            flow_name=intent_def.flow_name,
            required_slots=intent_def.required_slots,
            suggested_actions=intent_def.suggested_actions,
        )

    # ── Build classifier prompt ────────────────────────────────────────
    intent_list_lines = "\n".join(
        f'- "{name}": {defn.description}'
        for name, defn in INTENTS.items()
    )

    # Include last 2 exchange pairs for context (4 messages max)
    recent_turns: list[str] = []
    eligible = [m for m in conversation_history if m.get("role") in ("user", "assistant") and m.get("content")]
    for m in eligible[-4:]:
        role = m["role"].upper()
        content = (m.get("content") or "")[:200]
        recent_turns.append(f"{role}: {content}")
    recent_ctx = "\n".join(recent_turns) if recent_turns else "(no prior context)"

    system_prompt = (
        "You are an intent classifier for a banking chatbot.\n"
        "Respond ONLY with valid JSON — no explanation, no markdown.\n\n"
        f"Available intents:\n{intent_list_lines}\n\n"
        'Output format: {"intent": "<name>", "confidence": <0.0-1.0>}'
    )
    user_prompt = (
        f"Recent conversation:\n{recent_ctx}\n\n"
        f"Classify this message: {msg}"
    )

    # ── LLM call ───────────────────────────────────────────────────────
    intent_name = "general_faq"
    confidence = 0.5

    try:
        from litellm import acompletion
        from app.config import settings

        model = settings.model_name
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

        response = await acompletion(**kwargs)
        raw = (response.choices[0].message.content or "").strip()

        # Extract JSON — model may wrap it in ```json...```
        json_match = re.search(r"\{[^{}]+\}", raw, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            intent_name = str(data.get("intent", "general_faq"))
            confidence = float(data.get("confidence", 0.7))
            # Validate against known intents
            if intent_name not in INTENTS:
                intent_name = "general_faq"
                confidence = 0.4
        else:
            logger.debug("Classifier returned non-JSON: %r", raw[:100])

    except Exception as exc:
        logger.warning("Intent classification LLM call failed: %s — defaulting to general_faq", exc)

    intent_def = INTENTS.get(intent_name, FALLBACK_INTENT)
    is_negative = detect_negative_sentiment(message)

    return ClassificationResult(
        intent=intent_name,
        confidence=confidence,
        is_clarification=False,
        is_abort=False,
        is_negative_sentiment=is_negative,
        suggested_profile=intent_def.profile,
        flow_name=intent_def.flow_name,
        required_slots=intent_def.required_slots,
        suggested_actions=intent_def.suggested_actions,
    )
