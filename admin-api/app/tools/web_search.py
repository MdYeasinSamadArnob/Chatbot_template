"""
Web search tool — template for plugging in a real search API.

Currently returns a mock response with clear instructions for wiring
to Brave Search or SerpAPI. To enable real search, set BRAVE_API_KEY
in .env and uncomment the httpx block.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from app.tools.base import register_tool


class WebSearchInput(BaseModel):
    query: str = Field(..., description="The search query to look up")
    max_results: int = Field(default=3, ge=1, le=10, description="Maximum number of results to return")


@register_tool(
    "web_search",
    (
        "Search the web for current information, news, or facts. "
        "Use this when you need up-to-date information that may not be in your training data."
    ),
    WebSearchInput,
)
async def web_search(args: WebSearchInput, memory=None) -> str:
    """
    To enable real search, pick one of:

    ── Option A: Brave Search ─────────────────────────────────────────────
    import httpx
    brave_key = os.environ.get("BRAVE_API_KEY")
    if brave_key:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": brave_key, "Accept": "application/json"},
                params={"q": args.query, "count": args.max_results},
            )
            data = resp.json()
            results = data.get("web", {}).get("results", [])
            lines = [f"[{r['title']}]({r['url']})\n{r.get('description', '')}" for r in results]
            return "\n\n".join(lines) or "No results found."

    ── Option B: SerpAPI ──────────────────────────────────────────────────
    import httpx
    serp_key = os.environ.get("SERPAPI_API_KEY")
    if serp_key:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://serpapi.com/search",
                params={"q": args.query, "num": args.max_results, "api_key": serp_key},
            )
            ...
    """
    # ── Mock response ───────────────────────────────────────────────────────
    brave_key = os.environ.get("BRAVE_API_KEY")
    if brave_key:
        # Real Brave search (uncomment when key is available)
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={
                        "X-Subscription-Token": brave_key,
                        "Accept": "application/json",
                    },
                    params={"q": args.query, "count": args.max_results},
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("web", {}).get("results", [])
                if not results:
                    return f"No results found for: {args.query}"
                lines = [
                    f"**{r['title']}**\n{r.get('description', 'No description')}\n{r['url']}"
                    for r in results[: args.max_results]
                ]
                return "\n\n---\n\n".join(lines)
        except Exception as exc:
            return f"Search failed: {exc}"

    # ── Mock fallback ────────────────────────────────────────────────────────
    return (
        f"[Mock Web Search — query: '{args.query}']\n\n"
        "Real search is not configured. To enable it:\n"
        "1. Get a Brave Search API key from https://brave.com/search/api/\n"
        "2. Add BRAVE_API_KEY=your_key to backend/.env\n\n"
        "Example mock result: This is where live web results would appear."
    )
