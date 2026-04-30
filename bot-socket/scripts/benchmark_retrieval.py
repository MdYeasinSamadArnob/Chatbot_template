#!/usr/bin/env python3
"""Simple KB retrieval benchmark for top-k quality checks.

Usage:
  ../.venv/bin/python scripts/benchmark_retrieval.py
  ../.venv/bin/python scripts/benchmark_retrieval.py --top-k 3 --language bn
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.vector_search import VectorSearchInput, search_banking_knowledge


DEFAULT_QUERIES = [
    "How can I download statement?",
    "কার্ড হারিয়ে গেলে কী করব?",
    "BEFTN transfer limit",
    "How to add beneficiary?",
    "আমি পাসওয়ার্ড ভুলে গেছি",
    "How to open DPS?",
    "Can I transfer to bKash?",
    "RTGS charge",
]


async def run_once(query: str, top_k: int, language: str | None):
    args = VectorSearchInput(query=query, top_k=top_k, language=language)
    payload_text = await search_banking_knowledge(args)
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return {
            "query": query,
            "count": 0,
            "top_titles": [],
            "source_ids": [],
            "note": payload_text,
        }
    sources = payload.get("sources") or []
    return {
        "query": query,
        "count": len(sources),
        "top_titles": [s.get("document_title", "") for s in sources[:3]],
        "source_ids": [s.get("id", "") for s in sources[:3]],
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark hybrid retrieval quality")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--language", type=str, default=None)
    args = parser.parse_args()

    results = []
    for q in DEFAULT_QUERIES:
        try:
            r = await run_once(q, args.top_k, args.language)
            results.append(r)
        except Exception as exc:
            results.append({"query": q, "error": str(exc), "count": 0, "top_titles": [], "source_ids": []})

    ok = sum(1 for r in results if r.get("count", 0) > 0 and not r.get("error"))

    print("Retrieval benchmark summary")
    print(f"- queries: {len(results)}")
    print(f"- with_results: {ok}")
    print(f"- no_results_or_errors: {len(results) - ok}")
    print()

    for r in results:
        print(f"Q: {r['query']}")
        if r.get("error"):
            print(f"  error: {r['error']}")
        elif r.get("note"):
            print(f"  note: {r['note']}")
        else:
            print(f"  top3_titles: {r['top_titles']}")
            print(f"  top3_ids: {r['source_ids']}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
