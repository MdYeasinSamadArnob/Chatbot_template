"""
FastAPI + Socket.IO application entry point.

Services mounted:
  - FastAPI app under /api (profiles, health)
  - Socket.IO ASGI middleware at the root for WebSocket transport

Startup order:
  1. Import app.tools  → triggers @register_tool decorators
  2. Import socket_handlers → registers Socket.IO events
  3. Mount API router on FastAPI
  4. Wrap with Socket.IO ASGI app
  5. init_db() creates tables if they don't exist
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import socketio

# ── Tool auto-registration (must happen before router or sio is used) ─────
import app.tools  # noqa: F401
import app.tools.escalate_tool  # noqa: F401 — registers escalate_to_human

from app.api.chat import router as chat_router
from app.api.socket_handlers import sio
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── FastAPI app ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        from app.db.connection import init_db
        await init_db()
    except Exception as exc:
        logger.warning("DB init failed (postgres may not be ready yet): %s", exc)

    try:
        from app.tools.vector_search import warmup_embedding
        await warmup_embedding()
    except Exception as exc:
        logger.warning("Embedding warmup error: %s", exc)

    from app.tools.registry import registry
    logger.info(
        "Bot Socket API starting. Model=%s  Tools=%s",
        settings.model_name,
        registry.tool_names(),
    )
    yield
    logger.info("Bot Socket API shutting down.")


_fastapi_app = FastAPI(
    title="Bot Socket API",
    description="Chat + Socket.IO API for bot-ui (DMZ).",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

_fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Conversation-Id"],
)

_fastapi_app.include_router(chat_router)


# ── Wrap with Socket.IO ASGI ───────────────────────────────────────────────
# Socket.IO handles WebSocket upgrades; HTTP falls through to FastAPI.

app = socketio.ASGIApp(sio, other_asgi_app=_fastapi_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port)

