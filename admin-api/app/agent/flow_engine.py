"""
Flow engine — drives multi-step slot-filling conversations.

Flow state is stored in session_state["_flow"]:
{
    "flow_name":          str,
    "collected_slots":    {slot_name: value, ...},
    "current_step_index": int,
    "started_at":         ISO timestamp,
    "last_activity_at":   ISO timestamp,
}

Usage (in socket_handlers.py):
    engine = FlowEngine.from_session(session_state)
    if engine:
        result = engine.advance(user_input, session_state)
        if result.is_complete:
            # hand off completion_context to the agent loop
        elif result.is_aborted:
            # respond with abort_confirmation
        else:
            # emit result.next_question + result.quick_replies
    else:
        # no active flow — run normal intent → agent routing
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.agent.flow_definitions import (
    ConversationalFlow,
    FlowStep,
    format_date_range_label,
    get_flow,
)
# detect_abort removed — abort decisions are now made by the classifier/router

logger = logging.getLogger(__name__)

FLOW_MAX_AGE_MINUTES = 30


# ── Result ─────────────────────────────────────────────────────────────────

@dataclass
class FlowResult:
    next_question: Optional[str]
    """Text to emit as the next bot message. None when complete or aborted."""

    quick_replies: list[dict] = field(default_factory=list)

    is_complete: bool = False
    is_aborted: bool = False
    paused_for_faq: bool = False
    """True when user asked a side question — caller handles FAQ then resumes."""

    collected_slots: dict[str, Any] = field(default_factory=dict)
    completion_context: Optional[str] = None
    """Formatted completion text ready to send as the final bot response."""


# ── Engine ─────────────────────────────────────────────────────────────────

class FlowEngine:

    def __init__(self, flow: ConversationalFlow) -> None:
        self.flow = flow

    # ── Factory methods ────────────────────────────────────────────────

    @classmethod
    def from_session(cls, session_state: dict) -> Optional["FlowEngine"]:
        """Reconstruct engine from session_state. Returns None if no active or expired flow."""
        flow_state = session_state.get("_flow")
        if not flow_state:
            return None

        # Expiry check
        started_str = flow_state.get("started_at", "")
        if started_str:
            try:
                started_at = datetime.fromisoformat(started_str)
                age = (datetime.now(tz=timezone.utc) - started_at).total_seconds() / 60
                if age > FLOW_MAX_AGE_MINUTES:
                    logger.info("Flow '%s' expired after %.1f minutes", flow_state.get("flow_name"), age)
                    cls.clear(session_state)
                    return None
            except (ValueError, TypeError):
                pass

        flow = get_flow(flow_state.get("flow_name", ""))
        if not flow:
            cls.clear(session_state)
            return None

        return cls(flow)

    @classmethod
    def activate(cls, flow_name: str, session_state: dict) -> Optional["FlowEngine"]:
        """Start a new flow, overwriting any previous state."""
        flow = get_flow(flow_name)
        if not flow:
            return None
        now = datetime.now(tz=timezone.utc).isoformat()
        session_state["_flow"] = {
            "flow_name": flow_name,
            "collected_slots": {},
            "current_step_index": 0,
            "started_at": now,
            "last_activity_at": now,
        }
        return cls(flow)

    @classmethod
    def clear(cls, session_state: dict) -> None:
        session_state.pop("_flow", None)

    # ── Public interface ───────────────────────────────────────────────

    def get_intro(self) -> tuple[str, list[dict]]:
        """
        Return (intro_text + first_question, first_step_quick_replies).
        Called when a flow is first activated.
        """
        if not self.flow.steps:
            return self.flow.intro_text, []
        first = self.flow.steps[0]
        combined = f"{self.flow.intro_text}\n\n{first.prompt_text}"
        return combined, first.quick_replies

    def advance(
        self,
        user_input: str,
        session_state: dict,
        bank_name: str = "the bank",
        force_abort: bool = False,
    ) -> FlowResult:
        """
        Process the user's response to the current flow step.

        Handles:
          - Abort signals ("cancel", "never mind", etc.)
          - Slot extraction failures → re-ask with chips
          - Slot validation failures → error + re-ask
          - Forward-fill: extractor tries current slot; if None, checks remaining steps
          - Completion → formats completion_text_template and clears flow state
        """
        flow_state = session_state.setdefault("_flow", {})
        collected: dict[str, Any] = flow_state.setdefault("collected_slots", {})
        flow_state["last_activity_at"] = datetime.now(tz=timezone.utc).isoformat()

        # ── Abort (force_abort set by router based on classifier decision) ────────
        if force_abort:
            self.clear(session_state)
            return FlowResult(
                next_question=self.flow.abort_confirmation,
                is_aborted=True,
                collected_slots=dict(collected),
            )

        # ── Current step ───────────────────────────────────────────────
        current_idx: int = flow_state.get("current_step_index", 0)
        if current_idx >= len(self.flow.steps):
            return self._complete(session_state, bank_name)

        current_step: FlowStep = self.flow.steps[current_idx]

        # ── Try to extract the slot value ──────────────────────────────
        if current_step.extractor:
            extracted = current_step.extractor(user_input)
        else:
            extracted = user_input.strip() or None

        # ── Forward-fill: if extraction fails, try later steps ─────────
        if extracted is None:
            for lookahead_idx in range(current_idx + 1, len(self.flow.steps)):
                ls = self.flow.steps[lookahead_idx]
                if ls.extractor:
                    fwd = ls.extractor(user_input)
                    if fwd is not None:
                        collected[ls.slot] = fwd
                        flow_state["current_step_index"] = lookahead_idx + 1
                        # Still ask the original step
                        break

        if extracted is None:
            # Re-ask with optional clarification prefix
            ask_text = f"I didn't quite catch that. {current_step.prompt_text}"
            return FlowResult(
                next_question=ask_text,
                quick_replies=current_step.quick_replies,
                collected_slots=dict(collected),
            )

        # ── Validate ───────────────────────────────────────────────────
        if current_step.validator:
            error_msg = current_step.validator(extracted)
            if error_msg:
                return FlowResult(
                    next_question=f"{error_msg}\n\n{current_step.prompt_text}",
                    quick_replies=current_step.quick_replies,
                    collected_slots=dict(collected),
                )

        # ── Store slot, advance index ──────────────────────────────────
        collected[current_step.slot] = extracted
        next_idx = current_idx + 1

        # Skip optional already-filled slots
        while next_idx < len(self.flow.steps):
            ns = self.flow.steps[next_idx]
            if ns.optional and ns.slot in collected:
                next_idx += 1
            else:
                break

        flow_state["current_step_index"] = next_idx

        # ── Complete or continue ───────────────────────────────────────
        if next_idx >= len(self.flow.steps):
            return self._complete(session_state, bank_name)

        next_step = self.flow.steps[next_idx]
        return FlowResult(
            next_question=next_step.prompt_text,
            quick_replies=next_step.quick_replies,
            collected_slots=dict(collected),
        )

    # ── Private ────────────────────────────────────────────────────────

    def _complete(self, session_state: dict, bank_name: str) -> FlowResult:
        flow_state = session_state.get("_flow", {})
        collected: dict[str, Any] = flow_state.get("collected_slots", {})

        # Prepare template variables
        date_range = collected.get("date_range", "the requested period")
        date_range_label = (
            format_date_range_label(date_range) if isinstance(date_range, str) else str(date_range)
        )
        raw_type = collected.get("statement_type", "detailed") or "detailed"
        statement_type_display = raw_type.capitalize()

        # Avoid duplicate kwargs in str.format when collected slots contain
        # keys that are also passed explicitly below.
        explicit_keys = {
            "date_range",
            "date_range_label",
            "statement_type",
            "statement_type_display",
            "bank_name",
        }
        template_slots = {k: v for k, v in collected.items() if k not in explicit_keys}

        try:
            completion_text = self.flow.completion_text_template.format(
                date_range=date_range,
                date_range_label=date_range_label,
                statement_type=raw_type,
                statement_type_display=statement_type_display,
                bank_name=bank_name,
                **template_slots,
            )
        except KeyError as exc:
            logger.warning("Flow completion template key error: %s", exc)
            completion_text = "All details collected. Please follow the app instructions to proceed."

        self.clear(session_state)

        return FlowResult(
            next_question=None,
            is_complete=True,
            collected_slots=dict(collected),
            completion_context=completion_text,
        )
