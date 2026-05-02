"""
Rebuild render_blocks for ALL knowledge_chunks from their existing content_text in the DB.

Nothing is hardcoded — all content comes from the database itself.
Run whenever render_blocks gets out of sync with content_text.

Usage:
    python -m scripts._check_chunks
    python -m scripts._check_chunks --dry-run
    python -m scripts._check_chunks --match "statement"   # only matching doc titles
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------------
# Markdown → render_blocks parser (data-driven, no hardcoded content)
# ---------------------------------------------------------------------------

def _parse_markdown_to_render_blocks(text: str) -> list[dict]:
    """
    Parse plain markdown text (as stored in content_text) into render_blocks.
    Handles: headings, ordered lists, bullet lists, blockquotes, plain paragraphs.
    All content comes from the text argument — nothing hardcoded.
    """
    blocks: list[dict] = []
    lines = text.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i]

        # Strip the "[Title > Section]\n\n" prefix that kb_chunker adds
        if line.startswith("[") and "]" in line and i == 0:
            i += 1
            continue

        stripped = line.strip()

        # Heading: ## or ###
        heading_match = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            blocks.append({"type": "heading", "level": level, "content": heading_match.group(2).strip()})
            i += 1
            continue

        # Ordered or bullet list: collect consecutive list items
        ordered_match = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        bullet_match = re.match(r"^[-*•]\s+(.+)$", stripped)
        if ordered_match or bullet_match:
            variant = "ordered" if ordered_match else "bullet"
            items: list[str] = []
            while i < len(lines):
                l = lines[i].strip()
                om = re.match(r"^\d+[.)]\s+(.+)$", l)
                bm = re.match(r"^[-*•]\s+(.+)$", l)
                if om and variant == "ordered":
                    items.append(om.group(1).strip())
                    i += 1
                elif bm and variant == "bullet":
                    items.append(bm.group(1).strip())
                    i += 1
                elif not l:
                    # blank line inside list — peek ahead
                    if i + 1 < len(lines):
                        next_l = lines[i + 1].strip()
                        next_om = re.match(r"^\d+[.)]\s+", next_l)
                        next_bm = re.match(r"^[-*•]\s+", next_l)
                        if (next_om and variant == "ordered") or (next_bm and variant == "bullet"):
                            i += 1
                            continue
                    break
                else:
                    break
            if items:
                blocks.append({"type": "list", "variant": variant, "items": items})
            continue

        # Blockquote: > ...
        if stripped.startswith(">"):
            quote_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            content = " ".join(quote_lines).strip()
            if content:
                blocks.append({"type": "note", "content": content})
            continue

        # Blank line — skip
        if not stripped:
            i += 1
            continue

        # Plain paragraph — collect until blank line or structure boundary
        para_lines: list[str] = []
        while i < len(lines):
            l = lines[i].strip()
            if not l:
                break
            if re.match(r"^#{1,3}\s", l) or re.match(r"^\d+[.)]\s", l) or re.match(r"^[-*•]\s", l) or l.startswith(">"):
                break
            para_lines.append(l)
            i += 1
        content = " ".join(para_lines).strip()
        if content:
            blocks.append({"type": "text", "content": content})

    return blocks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def rebuild(match: str | None, dry_run: bool) -> None:
    from app.db.connection import init_db, AsyncSessionLocal
    from app.db.models import BankingKnowledge, KnowledgeDocument
    from sqlalchemy.future import select

    await init_db()

    async with AsyncSessionLocal() as session:
        stmt = select(BankingKnowledge).join(
            KnowledgeDocument, BankingKnowledge.document_id == KnowledgeDocument.id
        )
        if match:
            stmt = stmt.where(BankingKnowledge.document_title.ilike(f"%{match}%"))
        result = await session.execute(stmt)
        chunks = result.scalars().all()

    print(f"Found {len(chunks)} chunk(s)" + (f" matching '{match}'" if match else ""))

    updated = 0
    for chunk in chunks:
        if not chunk.content_text:
            print(f"  SKIP (no content_text): {chunk.document_title}")
            continue

        new_blocks = _parse_markdown_to_render_blocks(chunk.content_text)
        if not new_blocks:
            new_blocks = [{"type": "text", "content": chunk.content_text.strip()}]

        if dry_run:
            print(f"  [DRY RUN] {chunk.document_title} → {len(new_blocks)} block(s)")
            for b in new_blocks:
                print(f"    {b}")
            continue

        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_chunk = await session.get(BankingKnowledge, chunk.id)
                if db_chunk:
                    db_chunk.render_blocks = new_blocks
        updated += 1
        print(f"  ✓ {chunk.document_title} → {len(new_blocks)} block(s)")

    if not dry_run:
        print(f"\nDone — updated {updated} chunk(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild render_blocks from DB content_text")
    parser.add_argument("--match", default=None, help="Optional: only process chunks whose doc title contains this substring")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(rebuild(args.match, args.dry_run))


if __name__ == "__main__":
    main()
