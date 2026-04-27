# SQLAlchemy ORM models for conversations, messages, session_state, banking_knowledge
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Text, func
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

# Read-only table for banking knowledge (pre-populated)
class BankingKnowledge(Base):
    __tablename__ = "banking_knowledge"
    id = Column(Integer, primary_key=True)
    title = Column(String(256))
    content = Column(Text)
    image_urls = Column(ARRAY(Text))
    chunk_embedding = Column(Vector(1536))
    source_url = Column(String(512))
    created_at = Column(DateTime, server_default=func.now())
