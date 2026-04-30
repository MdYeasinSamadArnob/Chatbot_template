"""
Date/time tool — returns the current date, time, and timezone.

Demonstrates how a tool can interact with the agent memory (session state).
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.tools.base import register_tool


class GetCurrentTimeInput(BaseModel):
    timezone_name: str = Field(
        default="UTC",
        description="Timezone name, e.g. 'UTC', 'America/New_York', 'Europe/London'",
    )


@register_tool(
    "get_current_time",
    "Get the current date and time in a specified timezone. Use this when the user asks about the time or date.",
    GetCurrentTimeInput,
)
async def get_current_time(args: GetCurrentTimeInput, memory=None) -> str:
    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(args.timezone_name)
        now = datetime.now(tz=tz)
    except Exception:
        # Fall back to UTC if zone is invalid
        now = datetime.now(tz=timezone.utc)
        args.timezone_name = "UTC"

    return (
        f"Current time in {args.timezone_name}:\n"
        f"  Date: {now.strftime('%A, %B %d, %Y')}\n"
        f"  Time: {now.strftime('%H:%M:%S %Z')}\n"
        f"  ISO:  {now.isoformat()}"
    )
