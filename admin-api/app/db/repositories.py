# DB repository functions for conversations, messages, session state, escalations
from .models import Conversation, Message, SessionState, EscalationTicket, BankingKnowledge, KnowledgeDocument, FlowDefinition
from sqlalchemy.future import select
from sqlalchemy import delete, func as sqlfunc
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any, Optional, Literal
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
    priority_map = {
        "technical": "high",
        "complaint": "high",
        "account": "high",
        "general": "normal",
    }
    ticket = EscalationTicket(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        user_id=None,
        reason=reason,
        status="open",
        priority=priority_map.get(category, "normal"),
        metadata_={
            "reference_code": ticket_id,
            "category": category,
            **(metadata or {}),
        },
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
            "ticket_id": (
                (r.metadata_ or {}).get("reference_code")
                if isinstance(r.metadata_, dict)
                else str(r.id)
            ),
            "conversation_id": str(r.conversation_id),
            "reason": r.reason,
            "category": ((r.metadata_ or {}).get("category") if isinstance(r.metadata_, dict) else "general"),
            "priority": r.priority,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# ── Knowledge base ─────────────────────────────────────────────────────────

def _doc_to_dict(doc: KnowledgeDocument, chunk_count: int = 0) -> Dict[str, Any]:
    return {
        "id": str(doc.id),
        "title": doc.title,
        "category": doc.category,
        "subcategory": doc.subcategory,
        "intent_tags": doc.intent_tags or [],
        "version": doc.version,
        "author": doc.author,
        "is_published": doc.is_published,
        "embedding_status": doc.embedding_status,
        "embedded_at": doc.embedded_at.isoformat() if doc.embedded_at else None,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
        "chunk_count": chunk_count,
    }


def _chunk_to_dict(chunk: BankingKnowledge) -> Dict[str, Any]:
    return {
        "id": str(chunk.id),
        "document_id": str(chunk.document_id),
        "content_text": chunk.content_text,
        "chunk_index": chunk.chunk_index,
        "chunk_total": chunk.chunk_total,
        "section_anchor": chunk.section_anchor,
        "image_urls": chunk.image_urls or [],
        "source_url": chunk.source_url,
        "language": chunk.language,
        "is_active": chunk.is_active,
        "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
    }


async def kb_list_documents(
    session: AsyncSession,
    *,
    category: Optional[str] = None,
    search_title: Optional[str] = None,
    published_only: bool = False,
    limit: int = 25,
    offset: int = 0,
) -> tuple[List[Dict[str, Any]], int]:
    base_q = select(KnowledgeDocument)
    if category:
        base_q = base_q.where(KnowledgeDocument.category == category)
    if search_title:
        base_q = base_q.where(KnowledgeDocument.title.ilike(f"%{search_title}%"))
    if published_only:
        base_q = base_q.where(KnowledgeDocument.is_published == True)

    count_result = await session.execute(
        select(sqlfunc.count()).select_from(base_q.subquery())
    )
    total = count_result.scalar_one()

    rows_result = await session.execute(
        base_q.order_by(KnowledgeDocument.created_at.desc()).limit(limit).offset(offset)
    )
    docs = rows_result.scalars().all()

    result = []
    for doc in docs:
        count_r = await session.execute(
            select(sqlfunc.count()).where(BankingKnowledge.document_id == doc.id)
        )
        result.append(_doc_to_dict(doc, count_r.scalar_one()))
    return result, total


async def kb_get_document(session: AsyncSession, doc_id: str) -> Optional[Dict[str, Any]]:
    result = await session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return None
    count_r = await session.execute(
        select(sqlfunc.count()).where(BankingKnowledge.document_id == doc.id)
    )
    return _doc_to_dict(doc, count_r.scalar_one())


async def kb_get_document_with_chunks(
    session: AsyncSession, doc_id: str
) -> Optional[tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    result = await session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return None
    chunks_result = await session.execute(
        select(BankingKnowledge)
        .where(BankingKnowledge.document_id == doc_id)
        .order_by(BankingKnowledge.chunk_index)
    )
    chunks = chunks_result.scalars().all()
    return _doc_to_dict(doc, len(chunks)), [_chunk_to_dict(c) for c in chunks]


async def kb_create_document(
    session: AsyncSession,
    *,
    title: str,
    category: str,
    subcategory: Optional[str] = None,
    intent_tags: Optional[List[str]] = None,
    author: Optional[str] = None,
    is_published: bool = True,
) -> str:
    doc = KnowledgeDocument(
        id=uuid.uuid4(),
        title=title,
        category=category,
        subcategory=subcategory,
        intent_tags=intent_tags or [],
        author=author,
        is_published=is_published,
        embedding_status="pending",
    )
    session.add(doc)
    await session.flush()
    return str(doc.id)


async def kb_update_document(
    session: AsyncSession, doc_id: str, **fields
) -> bool:
    result = await session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return False
    allowed = {"title", "category", "subcategory", "intent_tags", "author", "is_published"}
    for k, v in fields.items():
        if k in allowed:
            setattr(doc, k, v)
    return True


async def kb_delete_document(session: AsyncSession, doc_id: str) -> bool:
    result = await session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return False
    await session.delete(doc)
    return True


async def kb_toggle_publish(session: AsyncSession, doc_id: str) -> Optional[bool]:
    result = await session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return None
    doc.is_published = not doc.is_published
    return doc.is_published


async def kb_set_embedding_status(
    session: AsyncSession,
    doc_id: str,
    status: Literal["pending", "processing", "ready", "failed"],
    embedded_at=None,
) -> None:
    result = await session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if doc:
        doc.embedding_status = status
        if embedded_at is not None:
            doc.embedded_at = embedded_at


async def kb_insert_chunk(
    session: AsyncSession,
    *,
    doc_id: str,
    document_title: str,
    content_text: str,
    embedding: List[float],
    chunk_index: int,
    chunk_total: int,
    section_anchor: Optional[str] = None,
    image_urls: Optional[List[str]] = None,
    source_url: Optional[str] = None,
    language: str = "en",
    document_type: str = "article",
) -> str:
    from app.config import settings
    if len(embedding) != settings.embedding_dims:
        raise ValueError(
            f"Embedding dimension mismatch: got {len(embedding)}, expected {settings.embedding_dims}"
        )
    chunk = BankingKnowledge(
        id=uuid.uuid4(),
        document_id=doc_id,
        document_title=document_title,
        document_type=document_type,
        content_text=content_text,
        content_type="text",
        chunk_embedding=embedding,
        chunk_index=chunk_index,
        chunk_total=chunk_total,
        section_anchor=section_anchor,
        image_urls=image_urls or [],
        source_url=source_url or "",
        language=language,
        is_active=True,
        relevance_score=1.0,
    )
    session.add(chunk)
    await session.flush()
    return str(chunk.id)


async def kb_replace_chunks(
    session: AsyncSession,
    doc_id: str,
    chunks_data: List[Dict[str, Any]],
) -> int:
    """
    INSERT-first, then DELETE-old in a single transaction.
    MVCC ensures readers see old chunks until commit — zero downtime.
    chunks_data: list of dicts with keys matching kb_insert_chunk kwargs (minus doc_id).
    Returns count of new chunks inserted.
    """
    from app.config import settings
    async with session.begin_nested():
        # 1. Insert all new chunks — collect their IDs
        new_ids = []
        for c in chunks_data:
            embedding = c["embedding"]
            if len(embedding) != settings.embedding_dims:
                raise ValueError(
                    f"Embedding dimension mismatch: got {len(embedding)}, expected {settings.embedding_dims}"
                )
            chunk = BankingKnowledge(
                id=uuid.uuid4(),
                document_id=doc_id,
                document_title=c.get("document_title", ""),
                document_type=c.get("document_type", "article"),
                content_text=c["content_text"],
                content_type="text",
                chunk_embedding=embedding,
                chunk_index=c["chunk_index"],
                chunk_total=c["chunk_total"],
                section_anchor=c.get("section_anchor"),
                image_urls=c.get("image_urls") or [],
                source_url=c.get("source_url") or "",
                language=c.get("language", "en"),
                is_active=True,
                relevance_score=1.0,
            )
            session.add(chunk)
            await session.flush()
            new_ids.append(chunk.id)

        # 2. Delete old chunks (all that weren't just inserted)
        await session.execute(
            delete(BankingKnowledge).where(
                BankingKnowledge.document_id == doc_id,
                BankingKnowledge.id.not_in(new_ids),
            )
        )
    return len(new_ids)


async def kb_list_categories(session: AsyncSession) -> List[str]:
    result = await session.execute(
        select(KnowledgeDocument.category)
        .distinct()
        .order_by(KnowledgeDocument.category)
    )
    return [row[0] for row in result.all()]


async def kb_get_stats(session: AsyncSession) -> Dict[str, int]:
    docs_r = await session.execute(select(sqlfunc.count()).select_from(KnowledgeDocument))
    chunks_r = await session.execute(select(sqlfunc.count()).select_from(BankingKnowledge))
    published_r = await session.execute(
        select(sqlfunc.count()).where(KnowledgeDocument.is_published == True)
    )
    cats_r = await session.execute(
        select(sqlfunc.count()).select_from(
            select(KnowledgeDocument.category).distinct().subquery()
        )
    )
    return {
        "documents": docs_r.scalar_one(),
        "chunks": chunks_r.scalar_one(),
        "published": published_r.scalar_one(),
        "categories": cats_r.scalar_one(),
    }


# ── Flow definition helpers ────────────────────────────────────────────────────

async def get_all_flow_definitions(session: AsyncSession) -> List[FlowDefinition]:
    result = await session.execute(
        select(FlowDefinition).order_by(FlowDefinition.flow_key)
    )
    return list(result.scalars().all())


async def get_flow_definition(
    session: AsyncSession, flow_key: str
) -> Optional[FlowDefinition]:
    result = await session.execute(
        select(FlowDefinition).where(FlowDefinition.flow_key == flow_key)
    )
    return result.scalar_one_or_none()


async def upsert_flow_definition(
    session: AsyncSession,
    flow_key: str,
    data: Dict[str, Any],
) -> FlowDefinition:
    result = await session.execute(
        select(FlowDefinition).where(FlowDefinition.flow_key == flow_key)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = FlowDefinition(flow_key=flow_key)
        session.add(row)
    for key, value in data.items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return row
