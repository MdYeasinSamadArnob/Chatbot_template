#!/usr/bin/env python3
"""
Seed the banking knowledge base from a JSON file.

Usage:
    python seed_knowledge.py --file faq.json
    python seed_knowledge.py --file faq.json --dry-run

JSON format (array of objects):
    [
      {
        "title": "How to Download Your Bank Statement",
        "content": "Step-by-step text content here...",
        "source_url": "https://www.bank.com/help/statement",
        "image_urls": ["https://cdn.bank.com/img/step1.png"]
      },
      ...
    ]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure the backend/app package is on sys.path when run from the scripts directory
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
    from app.db.connection import init_db, AsyncSessionLocal
    from app.db.repositories import upsert_knowledge_chunk

    articles = json.loads(Path(file_path).read_text(encoding="utf-8"))
    print(f"Found {len(articles)} articles in {file_path}")

    if dry_run:
        print("[DRY RUN] No data will be written.")

    if not dry_run:
        await init_db()

    for i, article in enumerate(articles, start=1):
        title = article.get("title", f"Article {i}")
        content = article.get("content", "")
        source_url = article.get("source_url", "")
        image_urls = article.get("image_urls", [])

        if not content.strip():
            print(f"  [{i}/{len(articles)}] SKIP (empty content): {title}")
            continue

        print(f"  [{i}/{len(articles)}] Embedding: {title[:60]}...")

        if dry_run:
            print(f"    → would insert {len(content)} chars")
            continue

        try:
            embedding = await embed_text(content)
        except Exception as exc:
            print(f"    ✗ Embedding failed: {exc}")
            continue

        try:
            async with AsyncSessionLocal() as session:
                row_id = await upsert_knowledge_chunk(
                    session=session,
                    title=title,
                    content=content,
                    embedding=embedding,
                    image_urls=image_urls,
                    source_url=source_url,
                )
            print(f"    ✓ Saved (id={row_id})")
        except Exception as exc:
            print(f"    ✗ DB insert failed: {exc}")

    print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed banking knowledge base.")
    parser.add_argument("--file", required=True, help="Path to JSON file with articles.")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing to DB.")
    args = parser.parse_args()

    asyncio.run(seed(args.file, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
