"""
Conversational flow definitions.

A ConversationalFlow is a series of FlowSteps, each collecting one
"slot" of data from the user. The FlowEngine (flow_engine.py) drives
the conversation through these steps.

Adding a new flow:
  1. Write extractor / validator functions below.
  2. Define a ConversationalFlow and add it to FLOWS.
  3. Reference flow_name in intent_taxonomy.py for the matching intent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class FlowStep:
    slot: str
    """Key under which the extracted value is stored in collected_slots."""

    prompt_text: str
    """Question shown to the user."""

    quick_replies: list[dict]
    """Chip options: [{"label": "...", "value": "..."}]"""

    optional: bool = False
    """If True and user says 'skip' or similar, slot is skipped."""

    extractor: Optional[Callable[[str], Any]] = None
    """Transform raw user text → structured value. Return None if extraction fails."""

    validator: Optional[Callable[[Any], Optional[str]]] = None
    """Validate extracted value. Return error string or None."""


@dataclass
class ConversationalFlow:
    name: str
    intent: str
    intro_text: str
    """Sent once when the flow is first activated, before the first question."""

    steps: list[FlowStep]
    completion_text_template: str
    """
    Format string for the completion message.
    Available variables depend on the flow; all collected_slots keys are available
    plus {bank_name}.
    """

    abort_confirmation: str = "No problem! Is there anything else I can help you with?"


# ── Extractor helpers ──────────────────────────────────────────────────────

def extract_date_range(text: str) -> Optional[str]:
    """Map natural language date range to a canonical value."""
    t = text.lower().strip()

    if re.search(r"last\s*30\s*day|এক\s*মাস|১\s*মাস|one\s*month|past\s*month", t):
        return "last_30_days"
    if re.search(r"last\s*60\s*day|two\s*month|দুই\s*মাস|২\s*মাস", t):
        return "last_60_days"
    if re.search(r"last\s*90\s*day|3\s*month|three\s*month|তিন\s*মাস|৩\s*মাস|last\s*quarter|quarter", t):
        return "last_90_days"
    if re.search(r"last\s*6\s*month|6\s*month|six\s*month|ছয়\s*মাস|৬\s*মাস|half\s*year", t):
        return "last_6_months"
    if re.search(r"(this|current|চলতি)\s*year|বছর|last\s*12\s*month|12\s*month", t):
        return "this_year"
    if re.search(r"last\s*year|গত\s*বছর|previous\s*year", t):
        return "last_year"

    # Custom date range: if the user provides explicit dates
    if re.search(r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}[-]\d{2}[-]\d{2}|from\s+\w|to\s+\w|between", t):
        return f"custom:{text.strip()}"

    return None  # Could not extract — FlowEngine will ask again


def extract_statement_type(text: str) -> Optional[str]:
    """Determine desired statement type from user input."""
    t = text.lower().strip()

    if re.search(r"detail|বিস্তারিত|full|complete|সম্পূর্ণ|all\s+transaction", t):
        return "detailed"
    if re.search(r"summary|সংক্ষিপ্ত|short|mini|brief|total|overview", t):
        return "summary"
    # Affirmative / default → detailed
    if re.search(r"\b(yes|ok|okay|any|either|both|sure|fine|doesn'?t\s+matter|default)\b", t):
        return "detailed"

    return None


# ── Date-range display labels ──────────────────────────────────────────────

DATE_RANGE_LABELS: dict[str, str] = {
    "last_30_days":  "Last 30 days",
    "last_60_days":  "Last 60 days",
    "last_90_days":  "Last 90 days",
    "last_6_months": "Last 6 months",
    "this_year":     "This year",
    "last_year":     "Last year",
}


def format_date_range_label(value: str) -> str:
    if value.startswith("custom:"):
        return value[7:]
    return DATE_RANGE_LABELS.get(value, value.replace("_", " ").title())


# ── Flow registry ──────────────────────────────────────────────────────────

FLOWS: dict[str, ConversationalFlow] = {

    "download_statement": ConversationalFlow(
        name="download_statement",
        intent="download_statement",
        intro_text=(
            "I can help you download your account statement! "
            "I just need a couple of quick details."
        ),
        steps=[
            FlowStep(
                slot="date_range",
                prompt_text="Which date range would you like the statement for?",
                quick_replies=[
                    {"label": "Last 30 days",  "value": "last 30 days"},
                    {"label": "Last 90 days",  "value": "last 90 days"},
                    {"label": "Last 6 months", "value": "last 6 months"},
                    {"label": "This year",     "value": "this year"},
                    {"label": "Custom range",  "value": "I need a custom date range"},
                ],
                extractor=extract_date_range,
            ),
            FlowStep(
                slot="statement_type",
                prompt_text=(
                    "Which type of statement do you need?\n\n"
                    "- **Detailed** — every transaction listed\n"
                    "- **Summary** — monthly totals only"
                ),
                quick_replies=[
                    {"label": "Detailed Statement", "value": "detailed"},
                    {"label": "Summary Statement",  "value": "summary"},
                ],
                optional=True,
                extractor=extract_statement_type,
            ),
        ],
        completion_text_template=(
            "Great! Here's how to download your **{statement_type}** statement "
            "for **{date_range_label}**:\n\n"
            "1. Open the **{bank_name}** mobile app\n"
            "2. Tap **My Account** → **Statements**\n"
            "3. Select the date range: **{date_range_label}**\n"
            "4. Choose **{statement_type_display}** and tap **Download**\n"
            "5. Your statement will be saved as a PDF to your device 📄\n\n"
            "Is there anything else I can help you with?"
        ),
        abort_confirmation=(
            "No problem! Let me know if you need help with anything else."
        ),
    ),

}


def get_flow(flow_name: str) -> Optional[ConversationalFlow]:
    return FLOWS.get(flow_name)


def apply_db_overrides(db_rows: list) -> None:
    """
    Merge DB-stored text overrides onto the in-memory FLOWS registry.

    Called at startup (and on reload) with a list of FlowDefinition ORM rows.
    Only non-None DB values overwrite the Python defaults; omitted fields are
    left untouched so a partial DB row still works.

    Preserves all Python extractor / validator functions — only text and
    quick_replies are overridable via the DB / admin UI.
    """
    import logging
    log = logging.getLogger(__name__)

    for row in db_rows:
        flow = FLOWS.get(row.flow_key)
        if flow is None:
            log.debug("apply_db_overrides: unknown flow_key %r — skipped", row.flow_key)
            continue

        if row.intro_text is not None:
            flow.intro_text = row.intro_text
        if row.abort_confirmation is not None:
            flow.abort_confirmation = row.abort_confirmation
        if row.completion_text_template is not None:
            flow.completion_text_template = row.completion_text_template

        # Per-step overrides: [{"slot": "date_range", "prompt_text": "...",
        #                       "quick_replies": [{"label": ..., "value": ...}]}]
        if row.steps_json:
            step_map = {s.slot: s for s in flow.steps}
            for step_override in row.steps_json:
                slot = step_override.get("slot")
                if slot and slot in step_map:
                    step = step_map[slot]
                    if step_override.get("prompt_text") is not None:
                        step.prompt_text = step_override["prompt_text"]
                    if step_override.get("quick_replies") is not None:
                        step.quick_replies = step_override["quick_replies"]

        log.info("apply_db_overrides: applied overrides for flow %r", row.flow_key)
