"""
Agent memory management — mimics Metabase's agent/memory.clj.

Three tiers:
  1. Conversation history   — exact OpenAI-format message list for LLM replay
  2. Session state          — structured dict persisted between API calls
                              (like Metabase's :queries / :charts / :todos)
  3. Long-term memory       — CrewAI LongTermMemory (SQLite) for cross-session facts

The global _sessions dict acts as the in-process session store.
In production, replace with Redis or a DB-backed store.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ── Long-term memory wrapper ───────────────────────────────────────────────

class LongTermStore:
    """
    Thin wrapper around CrewAI's LongTermMemory with SQLite backend.
    Falls back gracefully if crewai is not available.
    """

    def __init__(self, db_path: str) -> None:
        self._enabled = False
        try:
            from crewai.memory import LongTermMemory
            from crewai.memory.storage.ltm_sqlite_storage import LTMSQLiteStorage

            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
            self._ltm = LongTermMemory(
                storage=LTMSQLiteStorage(db_path=db_path)
            )
            self._enabled = True
        except Exception as exc:
            logger.warning(
                "CrewAI LongTermMemory unavailable (%s). "
                "Long-term memory will be disabled.",
                exc,
            )

    def save(self, task: str, output: str, metadata: dict | None = None) -> None:
        if not self._enabled:
            return
        try:
            self._ltm.save(
                task=task,
                output=output,
                metadata=metadata or {},
            )
        except Exception as exc:
            logger.debug("LTM save failed: %s", exc)

    def search(self, query: str, latest_n: int = 5) -> list[str]:
        if not self._enabled:
            return []
        try:
            results = self._ltm.search(task=query, latest_n=latest_n)
            return [str(r.get("output", "")) for r in (results or [])]
        except Exception as exc:
            logger.debug("LTM search failed: %s", exc)
            return []


# ── Conversation memory ────────────────────────────────────────────────────

class AgentMemory:
    """
    Per-conversation memory container.

    Mirrors Metabase's memory structure:
      :input-messages  → _messages    (LLM history)
      :steps-taken     → _steps       (per-iteration parts log)
      :state           → _state       (structured session data)
    """

    def __init__(self, conversation_id: str, persist_dir: str = "./memory_store") -> None:
        self.conversation_id = conversation_id

        # ── Short-term: exact LLM message history ──────────────────────
        self._messages: list[dict[str, Any]] = []

        # ── Per-iteration step log ──────────────────────────────────────
        self._steps: list[dict[str, Any]] = []

        # ── Session state (sent back to client as :data "state" parts) ──
        # Like Metabase's :queries / :charts / :todos
        self._state: dict[str, Any] = {
            "todos": [],
            "notes": {},
            "context": {},
        }

        # ── Long-term: CrewAI SQLite-backed cross-session memory ────────
        db_path = os.path.join(persist_dir, f"ltm_{conversation_id}.db")
        self._long_term = LongTermStore(db_path)
        # ── Intent summary log (LLM-generated, max 10 entries) ──────────
        # Records what the user wanted and the outcome of each turn.
        self._intent_log: list[dict[str, Any]] = []
    # ── Message management ──────────────────────────────────────────────────

    def add_user_message(self, content: str) -> None:
        self._messages.append({"role": "user", "content": content})

    def add_assistant_message(
        self,
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        msg: dict[str, Any] = {
            "role": "assistant",
            "content": content or "",
        }
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self._messages.append(msg)

    def add_tool_result(self, tool_call_id: str, result: str) -> None:
        self._messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result,
            }
        )

    def get_messages(self) -> list[dict[str, Any]]:
        """Return a copy of the conversation history for LLM consumption."""
        return list(self._messages)

    # ── Step log ────────────────────────────────────────────────────────────

    def add_step(self, parts: list[dict[str, Any]]) -> None:
        """Record one agent iteration's tool results."""
        self._steps.append({"parts": parts})

    # ── Session state ───────────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        return dict(self._state)

    def update_state(self, updates: dict[str, Any]) -> None:
        self._state.update(updates)

    def replace_state(self, new_state: dict[str, Any]) -> None:
        """Replace the full session state (supports key deletions)."""
        self._state = dict(new_state)

    # ── Long-term memory ────────────────────────────────────────────────────

    def remember(self, task: str, output: str) -> None:
        """Persist a fact for future conversations (cross-session)."""
        self._long_term.save(
            task=task,
            output=output,
            metadata={"conversation_id": self.conversation_id},
        )

    def recall(self, query: str, n: int = 5) -> list[str]:
        """Retrieve relevant long-term memories."""
        return self._long_term.search(query, latest_n=n)
    # ── Intent summary log ────────────────────────────────────────────────

    def record_intent(self, intent: str, summary: str) -> None:
        """Record a clean LLM-generated summary of a completed turn."""
        from datetime import datetime, timezone
        entry: dict[str, Any] = {
            "intent": intent,
            "summary": summary,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        self._intent_log.append(entry)
        if len(self._intent_log) > 10:
            self._intent_log = self._intent_log[-10:]
        # Mirror to long-term memory for cross-session recall
        self._long_term.save(
            task=intent,
            output=summary,
            metadata={"conversation_id": self.conversation_id},
        )

    def get_intent_context(self) -> str:
        """Return last 3 intent summaries as formatted context string, or '' if empty."""
        if not self._intent_log:
            return ""
        recent = self._intent_log[-3:]
        return "\n".join(f"- {e['intent']}: {e['summary']}" for e in recent)
    # ── PostgreSQL persistence ──────────────────────────────────────────────

    async def load_from_db(self) -> None:
        """Restore message history and session state from PostgreSQL."""
        try:
            from app.db.connection import AsyncSessionLocal
            from app.db.repositories import load_messages, load_session_state
            async with AsyncSessionLocal() as session:
                msgs = await load_messages(session, self.conversation_id)
                state = await load_session_state(session, self.conversation_id)
            self._messages = [
                {k: v for k, v in m.items() if k in ("role", "content", "tool_calls") and v is not None}
                for m in msgs
            ]
            # Filter out None tool_calls
            cleaned = []
            for m in msgs:
                entry: dict[str, Any] = {"role": m["role"], "content": m.get("content") or ""}
                if m.get("tool_calls"):
                    entry["tool_calls"] = m["tool_calls"]
                cleaned.append(entry)
            self._messages = cleaned
            if state:
                self._state.update(state)
                # Restore intent log and remove from state dict to keep _state clean
                self._intent_log = list(self._state.pop("_intent_log", []))
            logger.info(
                "Loaded %d messages and session state from DB for %s",
                len(self._messages),
                self.conversation_id,
            )
        except Exception as exc:
            logger.warning("Failed to load from DB (%s): %s", self.conversation_id, exc)

    async def save_to_db(self) -> None:
        """Flush message history and session state to PostgreSQL."""
        try:
            from app.db.connection import AsyncSessionLocal
            from app.db.repositories import save_messages, save_session_state
            # Include intent log in persisted state
            state_with_log = dict(self._state)
            state_with_log["_intent_log"] = self._intent_log
            async with AsyncSessionLocal() as session:
                await save_messages(session, self.conversation_id, self._messages)
                await save_session_state(session, self.conversation_id, state_with_log)
            logger.info(
                "Saved %d messages and state to DB for %s",
                len(self._messages),
                self.conversation_id,
            )
        except Exception as exc:
            logger.warning("Failed to save to DB (%s): %s", self.conversation_id, exc)

    def __repr__(self) -> str:
        return (
            f"<AgentMemory id={self.conversation_id!r} "
            f"messages={len(self._messages)} steps={len(self._steps)}>"
        )


# ── Global session store ───────────────────────────────────────────────────
# Keyed by conversation_id. Replace with Redis for multi-process deployments.

_sessions: dict[str, AgentMemory] = {}


def get_or_create_memory(
    conversation_id: str,
    persist_dir: str = "./memory_store",
) -> AgentMemory:
    if conversation_id not in _sessions:
        _sessions[conversation_id] = AgentMemory(conversation_id, persist_dir)
    return _sessions[conversation_id]


def clear_memory(conversation_id: str) -> None:
    _sessions.pop(conversation_id, None)


def list_conversations() -> list[str]:
    return list(_sessions.keys())
