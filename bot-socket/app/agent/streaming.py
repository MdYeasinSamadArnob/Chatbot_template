"""
AI SDK v4 line protocol formatters.

This module produces the exact same SSE line format used by Metabase's
agent/streaming.clj:

  0:"text delta"                         — text part
  9:{toolCallId, toolName, args}         — tool call part
  a:{toolCallId, result}                 — tool result part
  2:[{type, data}]                       — structured data part (state, navigate, etc.)
  3:"error message"                      — error part
  d:{finishReason, usage}                — finish part

The frontend lib/streaming.ts parses these exact prefixes.
"""

from __future__ import annotations

import json


def _j(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def text_part(text: str) -> str:
    """Stream a text delta to the client (prefix 0)."""
    return f"0:{_j(text)}\n"


def tool_call_part(tool_call_id: str, tool_name: str, args: dict) -> str:
    """Notify the client that the LLM is invoking a tool (prefix 9)."""
    return f"9:{_j({'toolCallId': tool_call_id, 'toolName': tool_name, 'args': args})}\n"


def tool_result_part(tool_call_id: str, result: str) -> str:
    """Send the result of a tool back to the client (prefix a)."""
    return f"a:{_j({'toolCallId': tool_call_id, 'result': result})}\n"


def data_part(data_type: str, data: object) -> str:
    """Send structured data (state, navigate_to, etc.) to the client (prefix 2)."""
    return f"2:{_j([{'type': data_type, 'data': data}])}\n"


def error_part(message: str) -> str:
    """Send an error to the client (prefix 3)."""
    return f"3:{_j(message)}\n"


def finish_part(
    finish_reason: str = "stop",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> str:
    """Signal stream completion with usage stats (prefix d)."""
    return f"d:{_j({'finishReason': finish_reason, 'usage': {'promptTokens': prompt_tokens, 'completionTokens': completion_tokens}})}\n"
