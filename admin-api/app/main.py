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
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.kb import router as kb_router
from app.api.flows import router as flows_router
from app.api.upload import router as upload_router
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── FastAPI app ────────────────────────────────────────────────────────────

_fastapi_app = FastAPI(
    title="Admin API",
    description="Knowledge-base management API for admin-ui (MZ).",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

_fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Conversation-Id"],
)

_fastapi_app.include_router(kb_router)
_fastapi_app.include_router(flows_router)
_fastapi_app.include_router(upload_router)


@_fastapi_app.on_event("startup")
async def on_startup() -> None:
    try:
        from app.db.connection import init_db
        await init_db()
    except Exception as exc:
        logger.warning("DB init failed (postgres may not be ready yet): %s", exc)

    # Ensure uploads directory exists and mount static files
    os.makedirs(settings.uploads_dir, exist_ok=True)
    _fastapi_app.mount(
        "/uploads",
        StaticFiles(directory=settings.uploads_dir),
        name="uploads",
    )

    logger.info("Admin API starting. Model=%s", settings.model_name)


@_fastapi_app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("Admin API shutting down.")


app = _fastapi_app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port)

