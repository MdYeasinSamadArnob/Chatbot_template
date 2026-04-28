# DB repository functions for conversations, messages, session state, escalations
from .models import Conversation, Message, SessionState, EscalationTicket, BankingKnowledge
from sqlalchemy.future import select
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any, Optional
import uuid

async def ensure_conversation(session: AsyncSession, conversation_id: str) -> None:
    """Upsert a conversation row so FK constraints are satisfied."""
    stmt = pg_insert(Conversation).values(id=conversation_id).on_conflict_do_nothing()
    await session.execute(stmt)

async def save_messages(session: AsyncSession, conversation_id: str, messages: List[Dict[str, Any]]) -> None:
    await ensure_conversation(session, conversation_id)
    await session.execute(delete(Message).where(Message.conversation_id == conversation_id))
    for msg in messages:
        db_msg = Message(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            role=msg["role"],
            content=msg.get("content") or "",
            tool_calls=msg.get("tool_calls"),
        )
        session.add(db_msg)
    await session.commit()

async def load_messages(session: AsyncSession, conversation_id: str) -> List[Dict[str, Any]]:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()
    return [
        {
            "role": m.role,
            "content": m.content,
            "tool_calls": m.tool_calls,
        }
        for m in messages
    ]

async def save_session_state(session: AsyncSession, conversation_id: str, state: Dict[str, Any]) -> None:
    await ensure_conversation(session, conversation_id)
    stmt = pg_insert(SessionState).values(
        conversation_id=conversation_id, state=state
    ).on_conflict_do_update(
        index_elements=["conversation_id"], set_={"state": state}
    )
    await session.execute(stmt)
    await session.commit()

async def load_session_state(session: AsyncSession, conversation_id: str) -> Dict[str, Any]:
    result = await session.execute(
        select(SessionState).where(SessionState.conversation_id == conversation_id)
    )
    row = result.scalar_one_or_none()
    return row.state if row else {}


# ── Escalation tickets ─────────────────────────────────────────────────────

async def create_escalation_ticket(
    session: AsyncSession,
    ticket_id: str,
    conversation_id: str,
    reason: str,
    category: str = "general",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Insert a new escalation ticket."""
    ticket = EscalationTicket(
        ticket_id=ticket_id,
        conversation_id=conversation_id,
        reason=reason,
        category=category,
        status="open",
        metadata_=metadata or {},
    )
    session.add(ticket)
    await session.commit()


async def list_escalation_tickets(
    session: AsyncSession,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List escalation tickets, optionally filtered by status."""
    query = select(EscalationTicket).order_by(EscalationTicket.created_at.desc()).limit(limit)
    if status:
        query = query.where(EscalationTicket.status == status)
    result = await session.execute(query)
    rows = result.scalars().all()
    return [
        {
            "ticket_id": r.ticket_id,
            "conversation_id": str(r.conversation_id),
            "reason": r.reason,
            "category": r.category,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# ── Knowledge base ─────────────────────────────────────────────────────────

async def upsert_knowledge_chunk(
    session: AsyncSession,
    title: str,
    content: str,
    embedding: List[float],
    image_urls: Optional[List[str]] = None,
    source_url: Optional[str] = None,
) -> int:
    """Insert or update a BankingKnowledge chunk. Returns the row id."""
    from .models import BankingKnowledge
    chunk = BankingKnowledge(
        title=title,
        content=content,
        image_urls=image_urls or [],
        chunk_embedding=embedding,
        source_url=source_url or "",
    )
    session.add(chunk)
    await session.flush()  # get the auto-incremented id
    await session.commit()
    return chunk.id

