"""
Application configuration via Pydantic Settings.
All values can be overridden via environment variables or a .env file.
"""

from __future__ import annotations

import json
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── LLM provider ─────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    model_name: str = "ollama/llama3.2"

    # ── Agent loop ───────────────────────────────────────────────────────
    max_iterations: int = 10
    default_temperature: float = 0.3

    # ── Memory ───────────────────────────────────────────────────────────
    memory_persist_dir: str = "./memory_store"

    # ── Server ───────────────────────────────────────────────────────────
    port: int = 9002
    cors_origins: list[str] = ["http://localhost:3001", "http://localhost:3002"]

    # ── Optional: external search APIs ──────────────────────────────────
    brave_api_key: str | None = None
    serpapi_api_key: str | None = None

    # ── Database ──────────────────────────────────────────────────────────
    postgres_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bankbot"

    # ── Embeddings ───────────────────────────────────────────────────────
    embedding_model: str = "nomic-embed-text"
    embedding_dims: int = 1024

    # ── Admin ───────────────────────────────────────────────────────────
    admin_secret: str = ""

    # ── File uploads ─────────────────────────────────────────────────────
    # Directory where uploaded images are stored (relative to CWD or absolute).
    # WARNING: files served from this directory are publicly accessible by URL.
    # Do not store sensitive files here.
    uploads_dir: str = "./uploads"
    upload_max_mb: int = 5

    # ── LLM thinking mode (Qwen3 / extended-reasoning models) ───────────
    # Set to False to disable chain-of-thought / thinking tokens.
    llm_thinking: bool = False

    # ── Optional separate model for intent classification ───────────────
    # Leave empty to use model_name. Set to a small/fast model (e.g. llama3.2:3b)
    # to keep the main model for high-quality responses.
    classifier_model: str = ""

    # ── Banking branding ─────────────────────────────────────────────────
    bank_name: str = "MyBank"

    # ── Debug logging ─────────────────────────────────────────────────────
    # Enables step-by-step routing and classifier decision logs.
    route_debug_logs: bool = True


settings = Settings()
