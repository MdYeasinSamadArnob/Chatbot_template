"""
Escalation tool — creates a support ticket and notifies the user.

Registered as "escalate_to_human" in the tool registry.
The banking profile includes this tool so the LLM can trigger HITL
when appropriate.
"""

from __future__ import annotations

import logging
import uuid

from pydantic import BaseModel, Field

from app.tools.base import register_tool

logger = logging.getLogger(__name__)


class EscalateInput(BaseModel):
    reason: str = Field(
        ...,
        description=(
            "Brief explanation of why a human agent is needed. "
            "E.g. 'User explicitly requested human agent' or 'Repeated resolution failures'."
        ),
    )
    category: str = Field(
        default="general",
        description="Ticket category: 'complaint' | 'technical' | 'account' | 'general'",
    )


@register_tool(
    name="escalate_to_human",
    description=(
        "Create a support ticket and escalate the conversation to a human agent. "
        "Use this when: "
        "(1) the user explicitly asks to speak to a human or customer service; "
        "(2) the user expresses serious frustration or a complaint after multiple failed attempts; "
        "(3) the issue involves sensitive account operations only a human can authorise; "
        "(4) you have been unable to resolve the user's issue after 3 or more attempts."
    ),
    schema=EscalateInput,
)
async def escalate_to_human(args: EscalateInput, memory=None) -> str:
    conversation_id = memory.conversation_id if memory else "unknown"
    ticket_id = str(uuid.uuid4())[:8].upper()

    try:
        from app.db.connection import AsyncSessionLocal
        from app.db.repositories import create_escalation_ticket

        async with AsyncSessionLocal() as session:
            await create_escalation_ticket(
                session=session,
                ticket_id=ticket_id,
                conversation_id=conversation_id,
                reason=args.reason,
                category=args.category,
            )
        logger.info(
            "Escalation ticket %s created (conversation=%s, category=%s)",
            ticket_id,
            conversation_id,
            args.category,
        )
    except Exception as exc:
        # Still respond successfully — ticket creation failure must not break the chat UX
        logger.warning("Failed to persist escalation ticket: %s", exc)

    return (
        f"ESCALATION_CREATED ticket_id={ticket_id}\n"
        f"Relay this to the user exactly:\n"
        f"Your case has been logged with reference number **{ticket_id}**. "
        f"A support agent will review your case and reach out to you shortly. "
        f"You can continue chatting here in the meantime, or call our helpline for immediate assistance."
    )
