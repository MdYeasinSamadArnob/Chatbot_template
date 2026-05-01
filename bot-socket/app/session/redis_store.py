"""
Redis-backed session cache for Bank Help Bot.

Design rules:
- PostgreSQL is always the source of truth.
- Redis is a write-through cache only.
- All Redis writes are best-effort: failures are logged as warnings and never
  propagate to callers.
- Rehydration uses SET NX (set-if-not-exists) — never overwrites a live key
  that a concurrent connection may already be using.
- All TTLs are 30 days (matches the useful lifetime of a conversation).
  Sliding TTL: every successful get_session() call resets the expiry.
- Redis connection timeout = settings.redis_timeout (default 1 s) so a slow
  or unavailable Redis server cannot block socket.io connect().

Key schema
──────────
  ba:user:{user_id}:conv     → conv_id  (str)
  ba:user:{user_id}:profile  → JSON { username, screen_context }
  ba:sess:{conv_id}          → JSON array of last-N message dicts
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_TTL_SECONDS = 30 * 24 * 3600   # 30 days
_MAX_SESSION_MESSAGES = 50


class RedisSessionStore:
    """
    Thin async wrapper around redis-py that degrades gracefully to a no-op
    when Redis is unavailable or not configured.
    """

    def __init__(self) -> None:
        self._client: Any = None
        self.available: bool = False

    async def init(self) -> None:
        """Attempt to connect to Redis.  Sets available=False silently on any failure."""
        from app.config import settings

        if not settings.redis_url:
            logger.debug("REDIS_URL not configured — Redis session cache disabled.")
            return

        try:
            import redis.asyncio as aioredis   # type: ignore[import]

            client = aioredis.from_url(
                settings.redis_url,
                socket_timeout=settings.redis_timeout,
                socket_connect_timeout=settings.redis_timeout,
                decode_responses=True,
            )
            # Verify connection is actually alive
            await client.ping()
            self._client = client
            self.available = True
            logger.info("Redis session cache connected: %s", settings.redis_url)
        except Exception as exc:
            logger.warning(
                "Redis unavailable (%s) — falling back to PostgreSQL only.", exc
            )
            self.available = False

    # ── Internal helpers ───────────────────────────────────────────────────

    async def _get(self, key: str) -> str | None:
        if not self.available:
            return None
        try:
            return await self._client.get(key)
        except Exception as exc:
            logger.warning("[redis] GET %s failed: %s", key, exc)
            return None

    async def _set(self, key: str, value: str, nx: bool = False) -> None:
        """SET with TTL.  If nx=True, uses SET NX (only write if key absent)."""
        if not self.available:
            return
        try:
            if nx:
                await self._client.set(key, value, ex=_TTL_SECONDS, nx=True)
            else:
                await self._client.set(key, value, ex=_TTL_SECONDS)
        except Exception as exc:
            logger.warning("[redis] SET %s failed: %s", key, exc)

    async def _expire(self, key: str) -> None:
        """Reset TTL to 30 d (sliding expiry on access)."""
        if not self.available:
            return
        try:
            await self._client.expire(key, _TTL_SECONDS)
        except Exception as exc:
            logger.debug("[redis] EXPIRE %s failed: %s", key, exc)

    # ── Public API ─────────────────────────────────────────────────────────

    async def get_user_conv(self, user_id: str) -> str | None:
        """Return the cached conv_id for this user, or None on miss/error."""
        return await self._get(f"ba:user:{user_id}:conv")

    async def set_user_conv(self, user_id: str, conv_id: str) -> None:
        await self._set(f"ba:user:{user_id}:conv", conv_id)

    async def get_user_profile(self, user_id: str) -> dict[str, str] | None:
        raw = await self._get(f"ba:user:{user_id}:profile")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    async def set_user_profile(self, user_id: str, username: str, screen_context: str) -> None:
        payload = json.dumps({"username": username, "screen_context": screen_context})
        await self._set(f"ba:user:{user_id}:profile", payload)

    async def get_session(self, conv_id: str) -> list[dict] | None:
        """
        Return cached message list for this conversation, or None on miss/error.
        Slides the TTL on every hit.
        """
        raw = await self._get(f"ba:sess:{conv_id}")
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                await self._expire(f"ba:sess:{conv_id}")
                return data
        except Exception:
            pass
        return None

    async def set_session(
        self, conv_id: str, messages: list[dict], nx: bool = False
    ) -> None:
        """
        Cache the last N messages for a conversation.

        nx=True  → only write if the key does not already exist (rehydration path).
        nx=False → overwrite (post-_persist write-through path).
        """
        # Keep only the most recent messages to bound Redis memory usage
        trimmed = messages[-_MAX_SESSION_MESSAGES:]
        payload = json.dumps(trimmed, default=str)
        await self._set(f"ba:sess:{conv_id}", payload, nx=nx)

    async def delete_session(self, conv_id: str) -> None:
        if not self.available:
            return
        try:
            await self._client.delete(f"ba:sess:{conv_id}")
        except Exception as exc:
            logger.debug("[redis] DEL ba:sess:%s failed: %s", conv_id, exc)


# ── Module-level singleton ─────────────────────────────────────────────────

_store: RedisSessionStore | None = None


def get_redis_store() -> RedisSessionStore:
    global _store
    if _store is None:
        _store = RedisSessionStore()
    return _store
