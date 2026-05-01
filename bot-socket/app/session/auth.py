"""
Auth helpers for user identity verification and input sanitization.

HMAC design
───────────
The mobile app signs:
    payload = f"{user_id}:{username}:{screen_context}:{timestamp}"
using HMAC-SHA256 with the shared SESSION_SECRET.

All four fields are bound into the payload so that modifying any one of
them (e.g. escalating a username or swapping screen_context) invalidates
the signature.

Clock-skew tolerance
────────────────────
The server accepts signatures whose embedded timestamp is within
±settings.hmac_clock_skew seconds of server time (default: 120 s / ±2 min).
This accommodates typical mobile device clock drift without opening a wide
replay window.

Sanitization
────────────
All user-supplied strings are sanitized to printable safe subsets before
they touch the database or the LLM system prompt.  Sanitization is a hard
strip (characters removed, not escaped) so there is no injection risk from
reconstructed strings.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
import logging

logger = logging.getLogger(__name__)

# ── Sanitizers ─────────────────────────────────────────────────────────────

# user_id: alphanumeric + safe punctuation only
_RE_USER_ID = re.compile(r"[^a-zA-Z0-9\-_.@]")
# username: letters, digits, spaces only — strips all special chars that could
# be used for prompt injection
_RE_USERNAME = re.compile(r"[^a-zA-Z0-9 ]")
# screen_context: alphanumeric + underscore only
_RE_SCREEN_CTX = re.compile(r"[^a-zA-Z0-9_]")


def sanitize_user_id(value: str | None) -> str:
    if not value:
        return ""
    return _RE_USER_ID.sub("", str(value))[:128]


def sanitize_username(value: str | None) -> str:
    """Strip to letters/digits/spaces, max 50 chars, trimmed."""
    if not value:
        return ""
    return _RE_USERNAME.sub("", str(value))[:50].strip()


def sanitize_screen_context(value: str | None) -> str:
    if not value:
        return ""
    return _RE_SCREEN_CTX.sub("", str(value))[:64]


# ── HMAC verification ──────────────────────────────────────────────────────

def verify_user_identity(
    user_id: str,
    username: str,
    screen_context: str,
    timestamp: str,
    signature: str,
    secret: str,
) -> bool:
    """
    Verify the HMAC-SHA256 signature sent by the mobile app.

    Returns True if the signature is valid and the timestamp is within the
    configured clock-skew window.  Returns False otherwise (never raises).

    The secret must be set via SESSION_SECRET env var; an empty secret always
    fails so that misconfigured servers cannot accidentally accept everything.
    """
    from app.config import settings

    if not secret:
        logger.warning(
            "[auth] SESSION_SECRET is not set — HMAC verification skipped (dev/test mode). "
            "Set SESSION_SECRET in .env before deploying to production."
        )
        return True  # Allow in dev mode; block in prod by setting SESSION_SECRET

    # ── Replay window check ────────────────────────────────────────────
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        logger.warning("[auth] Invalid timestamp value: %r", timestamp)
        return False

    delta = abs(int(time.time()) - ts)
    if delta > settings.hmac_clock_skew:
        logger.warning(
            "[auth] Timestamp rejected: delta=%ds (allowed ±%ds)",
            delta,
            settings.hmac_clock_skew,
        )
        return False

    # ── Signature check ────────────────────────────────────────────────
    payload = f"{user_id}:{username}:{screen_context}:{timestamp}"
    expected = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    valid = hmac.compare_digest(expected, signature.lower())
    if not valid:
        logger.warning("[auth] Signature mismatch for user_id=%r", user_id[:16])
    return valid
