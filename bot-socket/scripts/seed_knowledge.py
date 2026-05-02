#!/usr/bin/env python3
"""
Seed the banking knowledge base from a JSON file.

Usage:
    python scripts/seed_knowledge.py --file /path/to/your_articles.json
    python scripts/seed_knowledge.py --file /path/to/your_articles.json --dry-run

JSON format:
    [
      {
        "title":      "...",
        "content":    "...",
        "category":   "...",         (optional, default: "General")
        "subcategory":"...",         (optional)
        "source_url": "...",         (optional)
        "image_urls": ["..."],       (optional)
        "language":   "en"           (optional)
      },
      ...
    ]

Note: KB documents are managed through the Admin UI (localhost:3002).
      This script is only needed for bulk initial imports from a JSON export.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure backend/app is on sys.path when run from any directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def embed_text(text: str) -> list[float]:
    import httpx
    from app.config import settings

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.ollama_base_url}/api/embeddings",
            json={"model": settings.embedding_model, "prompt": text},
        )
        resp.raise_for_status()
        return resp.json()["embedding"]


async def seed(file_path: str, dry_run: bool = False) -> None:
    from app.config import settings
    from app.db.connection import init_db, AsyncSessionLocal
    from app.db.repositories import (
        kb_create_document,
        kb_insert_chunk,
        kb_set_embedding_status,
        kb_list_categories,
    )
    from app.agent.kb_chunker import chunk_document
    from datetime import datetime, timezone
    from sqlalchemy.future import select
    from app.db.models import KnowledgeDocument

    articles = json.loads(Path(file_path).read_text(encoding="utf-8"))
    print(f"Found {len(articles)} articles in {file_path}")

    if dry_run:
        print("[DRY RUN] No data will be written.")
        for i, a in enumerate(articles, 1):
            title = a.get("title", f"Article {i}")
            content = a.get("content", "")
            chunks = chunk_document(content, title)
            print(f"  [{i}/{len(articles)}] {title[:60]} → {len(chunks)} chunks")
        return

    await init_db()

    ok_count = 0
    fail_count = 0

    for i, article in enumerate(articles, start=1):
        title = article.get("title", f"Article {i}")
        content = article.get("content", "")
        category = article.get("category", "General")
        subcategory = article.get("subcategory")
        source_url = article.get("source_url", "")
        image_urls = article.get("image_urls", [])
        language = article.get("language", "en")

        if not content.strip():
            print(f"  [{i}/{len(articles)}] SKIP (empty content): {title}")
            fail_count += 1
            continue

        print(f"  [{i}/{len(articles)}] Processing: {title[:60]}...")

        # Idempotent: check if document with this title already exists
        async with AsyncSessionLocal() as session:
            existing = await session.execute(
                select(KnowledgeDocument).where(KnowledgeDocument.title == title)
            )
            existing_doc = existing.scalar_one_or_none()

        if existing_doc:
            print(f"    → already exists (id={existing_doc.id}), skipping")
            ok_count += 1
            continue

        # Create document header
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    doc_id = await kb_create_document(
                        session,
                        title=title,
                        category=category,
                        subcategory=subcategory,
                        is_published=True,
                    )
                    await kb_set_embedding_status(session, doc_id, "processing")
        except Exception as exc:
            print(f"    ✗ Failed to create document: {exc}")
            fail_count += 1
            continue

        # Chunk + embed
        chunks = chunk_document(content, title)
        embedded = 0
        failed_chunk = False

        for chunk in chunks:
            try:
                embedding = await embed_text(chunk.text)
                if len(embedding) != settings.embedding_dims:
                    print(
                        f"    ✗ Chunk {chunk.chunk_index}: dim mismatch "
                        f"(got {len(embedding)}, expected {settings.embedding_dims})"
                    )
                    failed_chunk = True
                    break
                async with AsyncSessionLocal() as session:
                    async with session.begin():
                        await kb_insert_chunk(
                            session,
                            doc_id=doc_id,
                            document_title=title,
                            content_text=chunk.text,
                            embedding=embedding,
                            chunk_index=chunk.chunk_index,
                            chunk_total=chunk.chunk_total,
                            section_anchor=chunk.section_heading or None,
                            image_urls=image_urls,
                            source_url=source_url,
                            language=language,
                        )
                embedded += 1
            except Exception as exc:
                print(f"    ✗ Chunk {chunk.chunk_index} failed: {exc}")
                failed_chunk = True
                break

        # Update embedding status
        final_status = "failed" if failed_chunk else "ready"
        embedded_at = datetime.now(timezone.utc) if not failed_chunk else None
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await kb_set_embedding_status(session, doc_id, final_status, embedded_at)

        if failed_chunk:
            print(f"    ✗ {title} (partial: {embedded}/{len(chunks)} chunks)")
            fail_count += 1
        else:
            print(f"    ✓ {title} ({embedded} chunks)")
            ok_count += 1

    # Build HNSW index after seeding
    print("\nBuilding HNSW index...")
    try:
        from sqlalchemy import text
        from app.db.connection import AsyncSessionLocal as SL
        async with SL() as session:
            async with session.begin():
                await session.execute(text(
                    "CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_hnsw_idx "
                    "ON knowledge_chunks USING hnsw (chunk_embedding vector_cosine_ops) "
                    "WITH (m = 16, ef_construction = 64)"
                ))
        print("  ✓ HNSW index ready")
    except Exception as exc:
        print(f"  ✗ HNSW index failed: {exc}")

    print(f"\nDone: {ok_count} ok, {fail_count} failed out of {len(articles)} articles")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed banking knowledge base")
    parser.add_argument("--file", required=True, help="Path to JSON knowledge file")
    parser.add_argument("--dry-run", action="store_true", help="Preview chunks without writing")
    args = parser.parse_args()
    asyncio.run(seed(args.file, dry_run=args.dry_run))
