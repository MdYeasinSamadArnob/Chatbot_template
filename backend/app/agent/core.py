"""
Agent orchestration loop — the heart of the system.

Mimics Metabase's run-agent-loop / loop-step pattern from agent/core.clj:

  run-agent-loop returns IReduceInit (Clojure reducible)
  → We use an AsyncGenerator for the same composable streaming semantics.

Flow per iteration (Metabase's "loop-step"):
  1. Build messages (system + history)
  2. call_llm() → get assistant response
  3. Stream text delta to client (0: lines)
  4. If tool calls → emit tool_call parts (9: lines)
  5. Execute all tools in parallel → asyncio.gather (like Metabase's virtual threads)
  6. Emit tool result parts (a: lines)
  7. Add results to memory → next iteration sees them
  8. Emit state update (2: lines)
  9. Loop until: no more tool calls OR max_iterations reached
 10. Emit finish part (d: line)

The AsyncGenerator approach lets the FastAPI StreamingResponse consume
chunks in real-time without buffering, giving the same streaming UX as
Metabase's transducer pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncGenerator, Awaitable, Callable

from litellm import acompletion

from app.agent.memory import AgentMemory
from app.agent.profiles import get_profile
from app.agent.prompts import build_system_prompt, build_reexplain_prompt
from app.agent.streaming import (
    data_part,
    error_part,
    finish_part,
    text_part,
    tool_call_part,
    tool_result_part,
)
from app.config import settings
from app.tools.registry import ToolDefinition, registry

logger = logging.getLogger(__name__)

# ── Llama 3.x artifact stripping ──────────────────────────────────────────
# Small models (llama3.2:3b) sometimes embed tool calls inside text content
# using <|python_tag|> markers or raw JSON. Strip them before display.

_PYTHON_TAG_RE = re.compile(r"<\|python_tag\|>.*", re.DOTALL)
# Matches various tool-call JSON formats that small models embed in text content
_BARE_TOOL_JSON_RE = re.compile(
    r'^\s*\{\s*"(?:type"\s*:\s*"function"|name"\s*:)',
    re.DOTALL,
)
# Matches a bare snake_case tool name on a line by itself, e.g. "Escalate_to_human"
_BARE_TOOL_NAME_RE = re.compile(
    r'^\s*[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\s*$'
)
# Matches role-label prefixes the model sometimes injects: "User:", "Assistant:"
_ROLE_LABEL_RE = re.compile(
    r'^(User|Assistant|Human|Bot)\s*:\s*',
    re.IGNORECASE,
)

# Known tool names (lower-cased for case-insensitive matching)
_KNOWN_TOOL_NAMES: frozenset[str] = frozenset({
    "escalate_to_human", "search_banking_knowledge", "vector_search",
    "web_search", "calculate", "calculator", "get_current_time",
    "get_datetime", "get_current_datetime",
})


def _strip_tool_artifacts(text: str) -> str:
    """Remove Llama 3.x internal tool-call markup and leaked tool/role labels."""
    if not text:
        return text
    # Strip <|python_tag|> … markers
    stripped, n = _PYTHON_TAG_RE.subn("", text)
    if n:
        text = stripped.strip()
    # Entire content is a tool-call JSON blob
    if _BARE_TOOL_JSON_RE.match(text):
        return ""
    # Entire content is just a bare tool name (e.g. "Escalate_to_human")
    if _BARE_TOOL_NAME_RE.match(text) and text.strip().lower() in _KNOWN_TOOL_NAMES:
        return ""
    # Strip role-label lines and fake dialogue transcript turns
    lines = text.split("\n")
    cleaned: list[str] = []
    skip_rest = False  # once we see a role label mid-response, drop everything after
    for line in lines:
        if _ROLE_LABEL_RE.match(line):
            skip_rest = True
        if skip_rest:
            continue
        cleaned.append(line)
    text = "\n".join(cleaned).rstrip()
    return text


def _try_recover_tool_call_from_text(text: str) -> dict | None:
    """
    Some Ollama models emit tool calls as plain JSON text instead of using the
    proper tool_calls API field.  This function attempts to parse that JSON and
    return a normalised tool-call dict so the executor can handle it correctly.

    Returns None if the text is not a recognisable tool-call payload.
    """
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None

    # Normalise: support {name, parameters}, {name, arguments},
    # and {type, function: {name, arguments}} wrapper formats.
    name: str = ""
    args: Any = {}
    if "function" in data and isinstance(data["function"], dict):
        name = data["function"].get("name", "")
        args = data["function"].get("arguments", {})
    else:
        name = data.get("name", "")
        args = data.get("parameters") or data.get("arguments") or {}

    if not name:
        return None

    return {
        "id": f"call_{name}_{abs(hash(stripped)) % 10**8}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args),
        },
    }


# ── LLM call helper ────────────────────────────────────────────────────────

async def _call_llm(
    messages: list[dict[str, Any]],
    tools_schema: list[dict] | None,
    temperature: float,
) -> Any:
    """
    Invoke the LLM via LiteLLM.

    LiteLLM acts as the provider-agnostic adapter (same role as
    Metabase's self/core.clj), routing to Ollama, OpenAI, Anthropic, etc.
    based on the MODEL_NAME prefix.
    """
    kwargs: dict[str, Any] = {
        "model": settings.model_name,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }

    # Auto-detect Ollama: if api_base points to Ollama and no provider prefix
    # is present, add "ollama/" so LiteLLM routes correctly.
    is_ollama_base = "11434" in settings.ollama_base_url or "ollama" in settings.ollama_base_url.lower()
    model_has_prefix = "/" in settings.model_name
    if is_ollama_base and not model_has_prefix:
        kwargs["model"] = f"ollama/{settings.model_name}"

    if "ollama/" in kwargs["model"]:
        kwargs["api_base"] = settings.ollama_base_url

    # Only attach tool schema when there are tools — some models error on empty list
    if tools_schema:
        kwargs["tools"] = tools_schema
        kwargs["tool_choice"] = "auto"

    return await acompletion(**kwargs)


# ── Streaming LLM helper (Socket.IO) ──────────────────────────────────────

async def _stream_llm_with_emitter(
    messages: list[dict[str, Any]],
    tools_schema: list[dict] | None,
    temperature: float,
    emit_fn: Callable[[str, Any], Awaitable[None]],
) -> tuple[str, list[dict[str, Any]], dict[str, int]]:
    """
    Call LLM with stream=True and emit text_delta events as chunks arrive.
    Assembles tool call deltas into complete dicts.

    Returns:
        (full_text, tool_calls_list, usage_dict)
        tool_calls items: {"id", "type", "function": {"name", "arguments"}}
    """
    kwargs: dict[str, Any] = {
        "model": settings.model_name,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    is_ollama_base = "11434" in settings.ollama_base_url or "ollama" in settings.ollama_base_url.lower()
    model_has_prefix = "/" in settings.model_name
    if is_ollama_base and not model_has_prefix:
        kwargs["model"] = f"ollama/{settings.model_name}"
    if "ollama/" in kwargs["model"]:
        kwargs["api_base"] = settings.ollama_base_url
    if tools_schema:
        kwargs["tools"] = tools_schema
        kwargs["tool_choice"] = "auto"

    text_parts: list[str] = []
    tool_calls_acc: dict[int, dict[str, Any]] = {}
    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
    thinking_ended = False  # emit thinking_end exactly once when output starts

    response = await acompletion(**kwargs)
    async for chunk in response:
        choice = chunk.choices[0]
        delta = choice.delta

        # ── Text chunk: emit immediately for token-by-token streaming ──
        if delta.content:
            cleaned = _strip_tool_artifacts(delta.content)
            if cleaned:
                if not thinking_ended:
                    await emit_fn("thinking_end", {})
                    thinking_ended = True
                text_parts.append(cleaned)
                await emit_fn("text_delta", {"delta": cleaned})

        # ── Tool call deltas: accumulate fragments into whole calls ────
        tc_list = getattr(delta, "tool_calls", None)
        if tc_list:
            if not thinking_ended:
                await emit_fn("thinking_end", {})
                thinking_ended = True
            for tc_delta in tc_list:
                idx = getattr(tc_delta, "index", 0) or 0
                if idx not in tool_calls_acc:
                    tool_calls_acc[idx] = {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                if tc_delta.id:
                    tool_calls_acc[idx]["id"] = tc_delta.id
                fn = getattr(tc_delta, "function", None)
                if fn:
                    if getattr(fn, "name", None):
                        tool_calls_acc[idx]["function"]["name"] += fn.name
                    if getattr(fn, "arguments", None):
                        tool_calls_acc[idx]["function"]["arguments"] += fn.arguments

        # ── Usage (last chunk, if provided) ────────────────────────────
        chunk_usage = getattr(chunk, "usage", None)
        if chunk_usage:
            usage["prompt_tokens"] = getattr(chunk_usage, "prompt_tokens", 0) or 0
            usage["completion_tokens"] = getattr(chunk_usage, "completion_tokens", 0) or 0

    full_text = "".join(text_parts)
    raw_tool_calls = [tool_calls_acc[i] for i in sorted(tool_calls_acc.keys())]
    return full_text, raw_tool_calls, usage


# ── Tool executor ──────────────────────────────────────────────────────────

async def _execute_tool(
    tool_def: ToolDefinition,
    raw_arguments: str | dict,
    memory: AgentMemory,
) -> str:
    """
    Execute a single tool, catching all exceptions gracefully.

    Mirrors Metabase's tool-executor-xf which catches per-tool errors
    and converts them to humanised error strings.
    """
    try:
        args_dict: dict[str, Any] = (
            json.loads(raw_arguments)
            if isinstance(raw_arguments, str)
            else (raw_arguments or {})
        )
        input_obj = tool_def.schema(**args_dict)

        if asyncio.iscoroutinefunction(tool_def.fn):
            result = await tool_def.fn(input_obj, memory=memory)
        else:
            loop = asyncio.get_running_loop()
            # Run sync tools in thread executor to avoid blocking the event loop
            result = await loop.run_in_executor(
                None,
                lambda o=input_obj, m=memory, f=tool_def.fn: f(o, memory=m),
            )
        return str(result)
    except Exception as exc:
        logger.warning("Tool %r raised: %s", tool_def.name, exc)
        return f"Error executing {tool_def.name}: {exc}"


# ── Main agent loop ────────────────────────────────────────────────────────

async def run_agent_loop(
    message: str,
    conversation_id: str,
    memory: AgentMemory,
    profile_name: str = "default",
    context: dict | None = None,
    session_state: dict | None = None,
) -> AsyncGenerator[str, None]:
    """
    The core plan→act→observe loop.

    Yields AI SDK v4 line-protocol strings that are forwarded directly
    to the client as a Server-Sent Events stream.

    This is the Python equivalent of Metabase's run-agent-loop:
      - profile → tool subset + system prompt + max_iterations
      - memory  → conversation history (short-term) + state (session)
      - long-term memory via CrewAI recalled before first iteration
    """
    context = context or {}
    profile = get_profile(profile_name)

    # ── Seed session state from the client (cross-request continuity) ──
    if session_state:
        memory.update_state(session_state)

    # ── Recall relevant long-term memories (CrewAI) ────────────────────
    ltm_hits = memory.recall(message, n=3)

    # ── Add user message to in-context history ─────────────────────────
    memory.add_user_message(message)

    # ── Build system prompt ────────────────────────────────────────────
    system_prompt = build_system_prompt(profile, context, ltm_hits or None)

    # ── Resolve profile tools → OpenAI function schema ─────────────────
    profile_tools = profile.get_tools()
    tools_schema = [t.to_openai_tool() for t in profile_tools] if profile_tools else None

    prompt_tokens_total = 0
    completion_tokens_total = 0
    consecutive_tool_errors = 0  # break loop if LLM keeps hallucinating tools

    # ── Iteration loop (Metabase: loop-step) ───────────────────────────
    for iteration in range(profile.max_iterations):
        logger.debug(
            "[%s] iteration %d/%d", conversation_id, iteration + 1, profile.max_iterations
        )

        messages = [
            {"role": "system", "content": system_prompt},
            *memory.get_messages(),
        ]

        # ── 1. Call LLM ────────────────────────────────────────────────
        try:
            response = await _call_llm(messages, tools_schema, profile.temperature)
        except Exception as exc:
            logger.error("[%s] LLM call failed: %s", conversation_id, exc)
            yield error_part(f"LLM call failed: {exc}")
            return

        # ── 2. Parse response ──────────────────────────────────────────
        if response.usage:
            prompt_tokens_total += getattr(response.usage, "prompt_tokens", 0) or 0
            completion_tokens_total += getattr(response.usage, "completion_tokens", 0) or 0

        choice = response.choices[0]
        msg = choice.message
        text_content: str = msg.content or ""
        raw_tool_calls: list = msg.tool_calls or []

        # Strip Llama 3.x tool-call artifacts that bleed into text content
        text_content = _strip_tool_artifacts(text_content)

        # ── 3. Persist assistant turn ──────────────────────────────────
        memory.add_assistant_message(
            content=text_content or None,
            tool_calls=[
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in raw_tool_calls
            ]
            if raw_tool_calls
            else None,
        )

        # ── 4. Stream text to client (AI SDK 0: part) ──────────────────
        if text_content:
            yield text_part(text_content)

        # ── 5. No tool calls → final answer, stop ─────────────────────
        if not raw_tool_calls:
            logger.debug("[%s] no tool calls — final answer", conversation_id)
            break

        # ── 6. Emit tool call notifications (AI SDK 9: parts) ─────────
        parsed_tool_calls: list[tuple[str, str, dict]] = []  # (id, name, args_dict)
        for tc in raw_tool_calls:
            try:
                args_dict = (
                    json.loads(tc.function.arguments)
                    if isinstance(tc.function.arguments, str)
                    else (tc.function.arguments or {})
                )
            except (json.JSONDecodeError, TypeError):
                args_dict = {}
            parsed_tool_calls.append((tc.id, tc.function.name, args_dict))
            yield tool_call_part(tc.id, tc.function.name, args_dict)

        # ── 7. Execute tools in parallel — track hallucinated tool names ──
        error_flags_sse: dict[str, bool] = {"has_unregistered": False}

        async def _exec(tc_id: str, tc_name: str, tc_args: dict) -> tuple[str, str]:
            tool_def = registry.get(tc_name)
            if tool_def is None:
                error_flags_sse["has_unregistered"] = True
                return tc_id, (
                    f"Tool '{tc_name}' does not exist. "
                    "Stop calling tools. Answer the user directly from your general banking knowledge."
                )
            result = await _execute_tool(tool_def, tc_args, memory)
            return tc_id, result

        results: list[tuple[str, str]] = await asyncio.gather(
            *[_exec(tid, tname, targs) for tid, tname, targs in parsed_tool_calls]
        )

        # ── 8. Emit tool results + update memory (AI SDK a: parts) ────
        step_parts: list[dict] = []
        for tool_call_id, result in results:
            memory.add_tool_result(tool_call_id, result)
            yield tool_result_part(tool_call_id, result)
            step_parts.append({"toolCallId": tool_call_id, "result": result})

        memory.add_step(step_parts)

        # ── 9. Emit state snapshot (AI SDK 2: part, type "state") ──────
        yield data_part("state", memory.get_state())

        # Force text-only on next iteration after a successful tool round
        if not error_flags_sse["has_unregistered"]:
            tools_schema = None

        # If any tool was hallucinated, strip tool schema so LLM must answer in text
        if error_flags_sse["has_unregistered"]:
            consecutive_tool_errors += 1
            tools_schema = None
            if consecutive_tool_errors >= 2:
                logger.warning("[%s] repeated hallucinated tools — forcing fallback", conversation_id)
                yield text_part(
                    "I'm sorry, I ran into a technical issue. Please try rephrasing your question, "
                    "or contact our support helpline for direct assistance."
                )
                break

    # ── Optionally persist key facts to long-term memory ──────────────
    # (In production, do this selectively based on conversation content)
    # memory.remember(task="conversation summary", output=message)

    # ── Final state + finish signal ────────────────────────────────────
    yield data_part("state", memory.get_state())
    yield finish_part(
        finish_reason="stop",
        prompt_tokens=prompt_tokens_total,
        completion_tokens=completion_tokens_total,
    )

# ── Socket.IO variant: emit_fn instead of AsyncGenerator ─────────────────────

async def run_agent_loop_with_emitter(
    message: str,
    conversation_id: str,
    memory: AgentMemory,
    emit_fn: Callable[[str, Any], Awaitable[None]],
    profile_name: str = "banking",
    context: dict | None = None,
    session_state: dict | None = None,    suggested_actions: list[dict] | None = None,) -> None:
    """
    Same plan→act→observe loop as run_agent_loop, but instead of
    yielding SSE lines it calls emit_fn(event_name, payload) — the
    Socket.IO server’s emit function bound to a specific client sid.
    """
    context = context or {}
    profile = get_profile(profile_name)

    if session_state:
        memory.update_state(session_state)

    ltm_hits = memory.recall(message, n=3)
    memory.add_user_message(message)
    system_prompt = build_system_prompt(profile, context, ltm_hits or None)

    profile_tools = profile.get_tools()
    tools_schema = [t.to_openai_tool() for t in profile_tools] if profile_tools else None

    prompt_tokens_total = 0
    completion_tokens_total = 0
    consecutive_tool_errors = 0  # break loop if LLM keeps hallucinating tools

    await emit_fn("thinking_start", {})

    for iteration in range(profile.max_iterations):
        logger.debug(
            "[%s] sio iteration %d/%d", conversation_id, iteration + 1, profile.max_iterations
        )

        messages = [
            {"role": "system", "content": system_prompt},
            *memory.get_messages(),
        ]

        # ── 1. Call LLM — stream final answers, non-stream tool-decision turns ──
        # Small models (llama3.2:3b) emit tool calls as raw JSON text when
        # streaming, so we use non-streaming while tools are in play and
        # only switch to streaming for the final text-only answer.
        try:
            if tools_schema:
                # Non-streaming: reliably separates tool_calls from text content
                response = await _call_llm(messages, tools_schema, profile.temperature)
                usage = response.usage
                prompt_tokens_total += getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens_total += getattr(usage, "completion_tokens", 0) or 0
                choice = response.choices[0]
                msg = choice.message
                text_content: str = _strip_tool_artifacts(msg.content or "")
                raw_tool_calls: list[dict[str, Any]] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in (msg.tool_calls or [])
                ]

                # Recovery: Ollama small models sometimes place the tool call as
                # plain JSON text in msg.content instead of msg.tool_calls.
                if not raw_tool_calls and text_content:
                    recovered = _try_recover_tool_call_from_text(text_content)
                    if recovered:
                        logger.debug(
                            "[%s] recovered tool call from text content: %s",
                            conversation_id, recovered["function"]["name"]
                        )
                        raw_tool_calls = [recovered]
                        text_content = ""  # suppress raw JSON from user view

                # Emit text now if the model gave text AND tool calls together
                if text_content:
                    await emit_fn("thinking_end", {})
                    await emit_fn("text_delta", {"delta": text_content})
            else:
                # Streaming: token-by-token for the final answer
                text_content, raw_tool_calls, iter_usage = await _stream_llm_with_emitter(
                    messages, None, profile.temperature, emit_fn
                )
                prompt_tokens_total += iter_usage.get("prompt_tokens", 0)
                completion_tokens_total += iter_usage.get("completion_tokens", 0)
        except Exception as exc:
            logger.error("[%s] LLM call failed: %s", conversation_id, exc)
            await emit_fn("error", {"message": f"LLM call failed: {exc}"})
            return

        # ── 2. Persist assistant turn ──────────────────────────────────
        memory.add_assistant_message(
            content=text_content or None,
            tool_calls=raw_tool_calls if raw_tool_calls else None,
        )

        # ── 3. No tool calls → final answer, stop ─────────────────────
        if not raw_tool_calls:
            # Ensure thinking indicator is gone even if no text was emitted
            await emit_fn("thinking_end", {})
            logger.debug("[%s] no tool calls — final answer", conversation_id)
            break

        # ── 4. Emit tool call notifications ───────────────────────────
        await emit_fn("thinking_end", {})
        parsed_tool_calls: list[tuple[str, str, dict]] = []
        for tc in raw_tool_calls:
            try:
                args_dict = (
                    json.loads(tc["function"]["arguments"])
                    if isinstance(tc["function"]["arguments"], str)
                    else (tc["function"]["arguments"] or {})
                )
            except (json.JSONDecodeError, TypeError):
                args_dict = {}
            parsed_tool_calls.append((tc["id"], tc["function"]["name"], args_dict))
            await emit_fn("tool_call", {
                "toolCallId": tc["id"],
                "toolName": tc["function"]["name"],
                "args": args_dict,
            })

        # Execute tools in parallel — track hallucinated (unregistered) tool names
        error_flags: dict[str, bool] = {"has_unregistered": False}

        async def _exec(tc_id: str, tc_name: str, tc_args: dict) -> tuple[str, str]:
            tool_def = registry.get(tc_name)
            if tool_def is None:
                error_flags["has_unregistered"] = True
                return tc_id, (
                    f"Tool '{tc_name}' does not exist. "
                    "Stop calling tools. Answer the user directly from your general banking knowledge."
                )
            result = await _execute_tool(tool_def, tc_args, memory)
            return tc_id, result

        results: list[tuple[str, str]] = await asyncio.gather(
            *[_exec(tid, tname, targs) for tid, tname, targs in parsed_tool_calls]
        )

        step_parts: list[dict] = []
        for tool_call_id, result in results:
            memory.add_tool_result(tool_call_id, result)
            await emit_fn("tool_result", {"toolCallId": tool_call_id, "result": result})
            step_parts.append({"toolCallId": tool_call_id, "result": result})

        memory.add_step(step_parts)
        # Emit inner state without suggested_actions — chips are delivered
        # exclusively in the finish payload to avoid stale-chip race conditions.
        _inner_state = {k: v for k, v in memory.get_state().items() if k != "suggested_actions"}
        await emit_fn("state", _inner_state)

        # ── Force text-only on next iteration ─────────────────────────
        # Small models (llama3.2:3b) tend to re-call tools repeatedly instead
        # of synthesising an answer.  Clearing the schema after the first
        # successful tool round guarantees the LLM must respond in plain text.
        if not error_flags["has_unregistered"]:
            tools_schema = None

        # If any tool was hallucinated, remove tool schema so the LLM is
        # forced to respond in plain text on the next (final) iteration.
        if error_flags["has_unregistered"]:
            consecutive_tool_errors += 1
            tools_schema = None  # next call → text only
            if consecutive_tool_errors >= 2:
                # LLM is stuck in a hallucination loop — emit fallback and stop
                logger.warning("[%s] repeated hallucinated tools — forcing fallback", conversation_id)
                await emit_fn("thinking_end", {})
                await emit_fn("text_delta", {
                    "delta": "I'm sorry, I ran into a technical issue. Please try rephrasing your question, or contact our support helpline for direct assistance."
                })
                break

    # Emit finish — include suggested_actions so frontend chips update atomically
    await emit_fn("thinking_end", {})
    await emit_fn("finish", {
        "finishReason": "stop",
        "usage": {
            "promptTokens": prompt_tokens_total,
            "completionTokens": completion_tokens_total,
        },
        "suggestedActions": suggested_actions or [],
    })


# ── Re-explain loop (Socket.IO) ────────────────────────────────────────────

async def run_reexplain_loop_with_emitter(
    user_message: str,
    last_bot_response: str,
    conversation_id: str,
    memory: AgentMemory,
    emit_fn: Callable[[str, Any], Awaitable[None]],
    suggested_actions: list[dict] | None = None,
) -> None:
    """
    Handle "I didn't understand" / clarification requests.

    Calls the LLM once with a special re-explain prompt — no tools,
    just a reformatted version of the previous response.
    """
    await emit_fn("thinking_start", {})

    system_prompt = build_reexplain_prompt(
        user_message=user_message,
        last_bot_response=last_bot_response,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        # Include recent conversation history for context
        *[m for m in memory.get_messages() if m.get("role") in ("user", "assistant")][-6:],
    ]

    try:
        text_content, _, usage = await _stream_llm_with_emitter(
            messages=messages,
            tools_schema=None,
            temperature=0.4,
            emit_fn=emit_fn,
        )
    except Exception as exc:
        logger.error("[%s] Re-explain LLM call failed: %s", conversation_id, exc)
        await emit_fn("error", {"message": "I'm having trouble rephrasing that. Please try asking again."})
        return

    memory.add_user_message(user_message)
    memory.add_assistant_message(content=text_content or None)

    await emit_fn("thinking_end", {})
    await emit_fn("finish", {
        "finishReason": "stop",
        "usage": {
            "promptTokens": usage.get("prompt_tokens", 0),
            "completionTokens": usage.get("completion_tokens", 0),
        },
        "suggestedActions": suggested_actions or [],
    })
