# Database connection setup for async SQLAlchemy + PgVector
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.postgres_url, echo=False, future=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def init_db() -> None:
    """Create extensions, all ORM tables, and idempotent column migrations / indexes."""
    from app.db.models import Base

    # Extensions — each in its own connection so a failure doesn't poison the transaction
    for ext_sql in [
        "CREATE EXTENSION IF NOT EXISTS vector",
        "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    ]:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(ext_sql))
        except Exception as exc:
            logger.warning("Extension SQL failed (may need superuser): %s — %s", ext_sql, exc)

    # Create all ORM tables (no-ops if already exist)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Idempotent column migrations — each in its own transaction so one failure doesn't block others
    migrations = [
        "ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS embedding_status TEXT NOT NULL DEFAULT 'pending'",
        "ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ",
        "ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS section_anchor TEXT",
    ]
    for sql in migrations:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql))
        except Exception as exc:
            logger.warning("Migration skipped: %s", exc)

    # Migrate relevance_score column type VARCHAR → FLOAT (safe no-op if already FLOAT)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "ALTER TABLE knowledge_chunks "
                "ALTER COLUMN relevance_score TYPE FLOAT USING "
                "CASE WHEN relevance_score::text ~ '^[0-9.]+$' "
                "     THEN relevance_score::text::FLOAT ELSE 1.0 END"
            ))
    except Exception:
        pass  # already FLOAT or column doesn't exist yet

    # Indexes — each in its own transaction
    indexes = [
        (
            "knowledge_chunks_doc_id_idx",
            "CREATE INDEX IF NOT EXISTS knowledge_chunks_doc_id_idx "
            "ON knowledge_chunks (document_id)",
        ),
        (
            "knowledge_chunks_embedding_hnsw_idx",
            "CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_hnsw_idx "
            "ON knowledge_chunks USING hnsw (chunk_embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)",
        ),
    ]
    for name, sql in indexes:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql))
            logger.info("Index ready: %s", name)
        except Exception as exc:
            logger.warning("Index %s failed: %s", name, exc)

    logger.info("Database tables and indexes initialised.")
