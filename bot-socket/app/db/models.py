# SQLAlchemy ORM models for conversations, messages, session_state, banking_knowledge, escalations
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Text, Boolean, Float, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import text
from sqlalchemy.types import Integer
from pgvector.sqlalchemy import Vector
import uuid

Base = declarative_base()

def default_uuid():
    return str(uuid.uuid4())

class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    extra_metadata = Column(JSON, nullable=True)
    # ── User identity (populated when an authenticated user connects) ──
    user_id = Column(String(128), nullable=True, index=True)
    username = Column(String(256), nullable=True)
    screen_context = Column(String(128), nullable=True)
    messages = relationship("Message", back_populates="conversation")

class Message(Base):
    __tablename__ = "messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    tool_calls = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    conversation = relationship("Conversation", back_populates="messages")

class SessionState(Base):
    __tablename__ = "session_state"
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), primary_key=True)
    state = Column(JSON, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

# Maps to the knowledge_chunks table populated by the KB editor
class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(Text, nullable=False)
    category = Column(Text, nullable=False)
    subcategory = Column(Text, nullable=True)
    intent_tags = Column(ARRAY(Text), nullable=True)
    version = Column(Integer, default=1, nullable=False)
    author = Column(Text, nullable=True)
    is_published = Column(Boolean, default=True, nullable=False)
    # embedding lifecycle: pending | processing | ready | failed
    embedding_status = Column(Text, default="pending", nullable=False)
    embedded_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    chunks = relationship(
        "BankingKnowledge",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class BankingKnowledge(Base):
    __tablename__ = "knowledge_chunks"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_title = Column(String(512))
    document_type = Column(String(64))
    content_text = Column(Text)          # plain text for LLM
    content_type = Column(String(64), default="text")
    content_raw = Column(Text)
    image_urls = Column(ARRAY(Text))
    render_blocks = Column(JSON)
    chunk_embedding = Column(Vector(1024))
    chunk_index = Column(Integer)
    chunk_total = Column(Integer)
    section_anchor = Column(Text, nullable=True)
    source_url = Column(String(512))
    language = Column(String(16))
    is_active = Column(Boolean, default=True)
    relevance_score = Column(Float, default=1.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("KnowledgeDocument", back_populates="chunks")


class EscalationTicket(Base):
    """Human-in-the-loop support tickets created when the bot escalates."""
    __tablename__ = "escalation_tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(String(128), nullable=True)
    reason = Column(Text, nullable=False)
    # Status: "open" → human review pending; "resolved" → handled
    status = Column(String(32), nullable=False, default="open")
    priority = Column(String(32), nullable=False, default="normal")
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

