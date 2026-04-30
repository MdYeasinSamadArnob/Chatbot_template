/**
 * PostgreSQL connection pool.
 * Only import this file from server-side code (API routes, Server Components).
 * Credentials are hardcoded here; use .env.local to override in production.
 */

import { Pool } from "pg";

// Module-level singleton — Next.js hot-reload can create multiple module
// instances in development, so we store the pool on the global object.
declare global {
  // eslint-disable-next-line no-var
  var __pgPool: Pool | undefined;
}

function getPool(): Pool {
  if (!globalThis.__pgPool) {
    globalThis.__pgPool = new Pool({
      host: process.env.DB_HOST ?? "10.11.200.99",
      port: Number(process.env.DB_PORT ?? 5432),
      database: process.env.DB_NAME ?? "banking_kb",
      user: process.env.DB_USER ?? "banking_kb_admin",
      password: process.env.DB_PASSWORD ?? "Era@1234",
      ssl: false,
      max: 10,
      idleTimeoutMillis: 30_000,
      connectionTimeoutMillis: 5_000,
    });
  }
  return globalThis.__pgPool;
}

export async function query<T = Record<string, unknown>>(
  sql: string,
  params?: unknown[]
): Promise<T[]> {
  const client = await getPool().connect();
  try {
    const result = await client.query(sql, params);
    return result.rows as T[];
  } finally {
    client.release();
  }
}

// ── Schema initialisation ──────────────────────────────────────────────────

let _schemaReady = false;

export async function ensureSchema(): Promise<void> {
  if (_schemaReady) return;

  const client = await getPool().connect();
  try {
    // Enable pgvector if available
    try {
      await client.query(`CREATE EXTENSION IF NOT EXISTS vector`);
    } catch {
      /* pgvector not installed — chunk_embedding column will be omitted */
    }

    // Parent documents table
    await client.query(`
      CREATE TABLE IF NOT EXISTS knowledge_documents (
        id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        title        TEXT NOT NULL,
        category     TEXT NOT NULL DEFAULT 'general',
        subcategory  TEXT,
        intent_tags  TEXT[] DEFAULT '{}',
        version      INT DEFAULT 1,
        author       TEXT,
        is_published BOOLEAN DEFAULT TRUE,
        created_at   TIMESTAMPTZ DEFAULT NOW(),
        updated_at   TIMESTAMPTZ DEFAULT NOW()
      )
    `);

    // Try with VECTOR column first; fall back without it if pgvector is absent
    try {
      await client.query(`
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
          id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          document_id     UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
          document_title  TEXT NOT NULL,
          document_type   TEXT NOT NULL DEFAULT 'faq',
          content_text    TEXT NOT NULL,
          content_type    TEXT NOT NULL DEFAULT 'wysiwyg_html',
          content_raw     TEXT,
          image_urls      TEXT[] DEFAULT '{}',
          render_blocks   JSONB DEFAULT '[]',
          chunk_embedding VECTOR(1024),
          chunk_index     INT NOT NULL DEFAULT 0,
          chunk_total     INT NOT NULL DEFAULT 1,
          source_url      TEXT,
          section_anchor  TEXT,
          language        TEXT DEFAULT 'en',
          is_active       BOOLEAN DEFAULT TRUE,
          relevance_score FLOAT,
          scraped_at      TIMESTAMPTZ,
          created_at      TIMESTAMPTZ DEFAULT NOW(),
          updated_at      TIMESTAMPTZ DEFAULT NOW()
        )
      `);
    } catch {
      await client.query(`
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
          id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          document_id     UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
          document_title  TEXT NOT NULL,
          document_type   TEXT NOT NULL DEFAULT 'faq',
          content_text    TEXT NOT NULL,
          content_type    TEXT NOT NULL DEFAULT 'wysiwyg_html',
          content_raw     TEXT,
          image_urls      TEXT[] DEFAULT '{}',
          render_blocks   JSONB DEFAULT '[]',
          chunk_index     INT NOT NULL DEFAULT 0,
          chunk_total     INT NOT NULL DEFAULT 1,
          source_url      TEXT,
          section_anchor  TEXT,
          language        TEXT DEFAULT 'en',
          is_active       BOOLEAN DEFAULT TRUE,
          relevance_score FLOAT,
          scraped_at      TIMESTAMPTZ,
          created_at      TIMESTAMPTZ DEFAULT NOW(),
          updated_at      TIMESTAMPTZ DEFAULT NOW()
        )
      `);
    }

    // Indexes
    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_kc_document
        ON knowledge_chunks (document_id, chunk_index)
    `);
    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_kc_type_active
        ON knowledge_chunks (document_type, is_active)
    `);
    await client.query(`
      CREATE INDEX IF NOT EXISTS idx_kd_updated
        ON knowledge_documents (updated_at DESC)
    `);

    _schemaReady = true;
  } finally {
    client.release();
  }
}
