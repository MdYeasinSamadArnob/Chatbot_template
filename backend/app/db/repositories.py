# DB repository functions for conversations, messages, session state
from .models import Conversation, Message, SessionState
from sqlalchemy.future import select
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any
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
