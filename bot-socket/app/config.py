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
    port: int = 9001
    cors_origins: list[str] = ["http://localhost:3001", "http://localhost:3002"]

    # ── Optional: external search APIs ──────────────────────────────────
    brave_api_key: str | None = None
    serpapi_api_key: str | None = None

    # ── Database ──────────────────────────────────────────────────────────
    postgres_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bankbot"

    # ── Embeddings ───────────────────────────────────────────────────────
    embedding_model: str = "nomic-embed-text"
    embedding_dims: int = 1024
    embedding_attempts: int = 1
    embedding_timeout_ms: int = 2200
    embedding_cache_ttl_seconds: int = 900
    embedding_cache_max_entries: int = 2048
    vector_hnsw_ef_search: int = 96
    vector_candidate_multiplier: int = 10
    sparse_candidate_multiplier: int = 6
    hybrid_dense_weight: float = 0.75
    hybrid_sparse_weight: float = 0.25
    hybrid_rrf_k: int = 60
    hybrid_min_dense_similarity: float = 0.20
    hybrid_lexical_boost: float = 0.12
    hybrid_max_chunks_per_document: int = 2

    # ── Admin ───────────────────────────────────────────────────────────
    admin_secret: str = ""

    # ── Session / identity ───────────────────────────────────────────────
    # SESSION_SECRET: required when authenticated users connect (HMAC signing).
    # Startup will fail with a clear error if this is missing and a signed
    # connection arrives.  Guest sessions (no user_id) never check this.
    session_secret: str = ""

    # Redis: optional.  If unset, the system falls back to PostgreSQL + in-memory.
    redis_url: str | None = None
    redis_timeout: float = 1.0          # socket / connect timeout in seconds

    # HMAC replay-window: reject tokens older than this many seconds (±).
    # 120 s (±2 min) is enough to absorb typical mobile clock drift.
    hmac_clock_skew: int = 120

    # ── LLM thinking mode (Qwen3 / extended-reasoning models) ───────────
    # Set to False to disable chain-of-thought / thinking tokens.
    llm_thinking: bool = False

    # ── Optional separate model for intent classification ───────────────
    # Leave empty to use model_name. Set to a small/fast model (e.g. llama3.2:3b)
    # to keep the main model for high-quality responses.
    classifier_model: str = ""

    # ── Latency tuning ───────────────────────────────────────────────────
    classifier_cache_ttl_seconds: int = 180
    classifier_cache_max_entries: int = 1024
    classifier_timeout_ms: int = 2800
    kb_prefetch_timeout_ms: int = 1200
    kb_prefetch_timeout_ms_degraded: int = 400
    disable_kb_tool_when_embedding_down: bool = True

    # Number of KB chunks fetched during the parallel pre-fetch (runs before the
    # agent loop). Higher = more recall for broad queries ("transfer money");
    # lower = faster. Keep at 6 unless latency is a concern.
    kb_prefetch_top_k: int = 6

    # When True, completed guided-flow responses are grounded in KB articles
    # via a focused LLM call instead of returning the static template string.
    # Set to False to revert to the old template-only behaviour.
    flow_kb_augment: bool = True

    # ── Embedding backend circuit breaker ────────────────────────────────
    embedding_breaker_failure_threshold: int = 3
    embedding_breaker_cooldown_seconds: int = 45

    # ── LLM request timeout ─────────────────────────────────────────────
    # Max seconds to wait for a single LLM completion (non-stream or stream).
    # Prevents indefinite hangs when Ollama is loading cold or crashes.
    llm_request_timeout_seconds: float = 90.0

    # ── Banking branding ─────────────────────────────────────────────────
    bank_name: str = "MyBank"

    # ── Debug logging ─────────────────────────────────────────────────────
    # Enables step-by-step routing and classifier decision logs.
    route_debug_logs: bool = True


settings = Settings()
