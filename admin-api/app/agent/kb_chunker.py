"""
Heading-aware document chunker for the Knowledge Base.

Strategy (in priority order):
  1. Split at ## / ### Markdown heading boundaries
  2. If a section exceeds max_chars → split at blank lines (paragraphs)
  3. If a paragraph exceeds max_chars → split at ". " (sentence boundary)

Every chunk is prefixed with "[{title} > {section_heading}]" so that the
embedding captures document and section context even for short chunks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ChunkData:
    text: str               # full text including "[Title > Section]" prefix
    section_heading: str    # raw heading text (empty string for intro section)
    chunk_index: int        # 0-based position within the document
    chunk_total: int = 0    # backfilled after all chunks are known


def _split_by_headings(content: str) -> list[tuple[str, str]]:
    """Return list of (heading, body_text) pairs. First pair may have empty heading."""
    heading_re = re.compile(r"^#{2,3}\s+(.+)$", re.MULTILINE)
    sections: list[tuple[str, str]] = []
    last_end = 0
    last_heading = ""

    for m in heading_re.finditer(content):
        body = content[last_end:m.start()].strip()
        if body or sections:
            sections.append((last_heading, body))
        last_heading = m.group(1).strip()
        last_end = m.end()

    # Remainder after last heading
    tail = content[last_end:].strip()
    if tail or not sections:
        sections.append((last_heading, tail))

    return sections


def _split_text(text: str, max_chars: int) -> list[str]:
    """Split text below max_chars using paragraphs then sentences."""
    if len(text) <= max_chars:
        return [text] if text else []

    # Try paragraph splits first
    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > max_chars:
            # Flush current, then sentence-split the long paragraph
            if current:
                chunks.append(current)
                current = ""
            sentences = re.split(r"(?<=\.)\s+", para)
            buf = ""
            for sent in sentences:
                if len(buf) + len(sent) + 1 > max_chars and buf:
                    chunks.append(buf.strip())
                    buf = sent
                else:
                    buf = (buf + " " + sent).strip() if buf else sent
            if buf:
                chunks.append(buf.strip())
        elif len(current) + len(para) + 2 > max_chars:
            if current:
                chunks.append(current)
            current = para
        else:
            current = (current + "\n\n" + para).strip() if current else para

    if current:
        chunks.append(current)

    return chunks if chunks else [text[:max_chars]]


def chunk_document(
    content: str,
    title: str,
    max_chars: int = 512,
) -> list[ChunkData]:
    """
    Split a document into chunks and prefix each with "[title > section]".

    Returns a list of ChunkData with chunk_total already set.
    """
    sections = _split_by_headings(content)
    raw_chunks: list[tuple[str, str]] = []  # (heading, chunk_text)

    for heading, body in sections:
        if not body:
            continue
        for piece in _split_text(body, max_chars):
            if piece.strip():
                raw_chunks.append((heading, piece.strip()))

    # Build ChunkData with contextual prefix
    result: list[ChunkData] = []
    total = len(raw_chunks)
    for idx, (heading, piece) in enumerate(raw_chunks):
        section_label = heading if heading else title
        prefix = f"[{title} > {section_label}]\n\n"
        result.append(ChunkData(
            text=prefix + piece,
            section_heading=heading,
            chunk_index=idx,
            chunk_total=total,
        ))

    return result
