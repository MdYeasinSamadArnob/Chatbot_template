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
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3001"]

    # ── Optional: external search APIs ──────────────────────────────────
    brave_api_key: str | None = None
    serpapi_api_key: str | None = None

    # ── Database ──────────────────────────────────────────────────────────
    postgres_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bankbot"

    # ── Embeddings ───────────────────────────────────────────────────────
    embedding_model: str = "nomic-embed-text"

    # ── Banking branding ─────────────────────────────────────────────────
    bank_name: str = "MyBank"


settings = Settings()
