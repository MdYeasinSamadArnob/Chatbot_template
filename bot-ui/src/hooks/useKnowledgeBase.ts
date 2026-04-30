"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// ── Types ──────────────────────────────────────────────────────────────────

export interface KBDocument {
  id: string;
  title: string;
  category: string;
  subcategory?: string;
  intent_tags: string[];
  version: number;
  author?: string;
  is_published: boolean;
  embedding_status: "pending" | "processing" | "ready" | "failed";
  embedded_at?: string;
  created_at?: string;
  updated_at?: string;
  chunk_count: number;
}

export interface KBChunk {
  id: string;
  document_id: string;
  content_text: string;
  chunk_index: number;
  chunk_total: number;
  section_anchor?: string;
  image_urls: string[];
  source_url?: string;
  language?: string;
  is_active: boolean;
  created_at?: string;
}

export interface KBStats {
  documents: number;
  chunks: number;
  published: number;
  categories: number;
}

export interface DocumentListFilter {
  category?: string;
  search?: string;
  published?: boolean;
  limit?: number;
  offset?: number;
}

export interface DocumentCreateData {
  title: string;
  category: string;
  subcategory?: string;
  intent_tags?: string[];
  author?: string;
  is_published?: boolean;
  content: string;
  source_url?: string;
  image_urls?: string[];
  language?: string;
}

export interface DocumentUpdateData {
  title?: string;
  category?: string;
  subcategory?: string;
  intent_tags?: string[];
  author?: string;
  is_published?: boolean;
}

// ── Helper ─────────────────────────────────────────────────────────────────

async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`/api/kb/${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`KB API error ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ── useDocuments ───────────────────────────────────────────────────────────

export function useDocuments(filter: DocumentListFilter = {}) {
  const [items, setItems] = useState<KBDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch_ = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filter.category) params.set("category", filter.category);
      if (filter.search) params.set("search", filter.search);
      if (filter.published != null) params.set("published", String(filter.published));
      params.set("limit", String(filter.limit ?? 25));
      params.set("offset", String(filter.offset ?? 0));

      const data = await apiFetch<{ items: KBDocument[]; total: number }>(
        `documents?${params.toString()}`
      );
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [filter.category, filter.search, filter.published, filter.limit, filter.offset]);

  useEffect(() => { fetch_(); }, [fetch_]);

  return { items, total, loading, error, refetch: fetch_ };
}

// ── useStats ───────────────────────────────────────────────────────────────

export function useStats() {
  const [stats, setStats] = useState<KBStats | null>(null);
  const fetch_ = useCallback(async () => {
    try {
      const data = await apiFetch<KBStats>("stats");
      setStats(data);
    } catch {
      // non-critical
    }
  }, []);
  useEffect(() => { fetch_(); }, [fetch_]);
  return { stats, refetch: fetch_ };
}

// ── useCategories ──────────────────────────────────────────────────────────

export function useCategories() {
  const [categories, setCategories] = useState<string[]>([]);
  useEffect(() => {
    apiFetch<{ categories: string[] }>("categories")
      .then((d) => setCategories(d.categories))
      .catch(() => {});
  }, []);
  return categories;
}

// ── useEmbeddingStatus (polls while processing) ────────────────────────────

export function useEmbeddingStatus(docId: string | null) {
  const [status, setStatus] = useState<KBDocument["embedding_status"] | null>(null);
  const [embeddedAt, setEmbeddedAt] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!docId) return;

    const poll = async () => {
      try {
        const data = await apiFetch<{ document: KBDocument }>(`documents/${docId}`);
        setStatus(data.document.embedding_status);
        setEmbeddedAt(data.document.embedded_at ?? null);
        if (data.document.embedding_status === "processing") {
          timerRef.current = setTimeout(poll, 2000);
        }
      } catch {
        // ignore transient errors during polling
      }
    };

    poll();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [docId]);

  return { status, embeddedAt };
}

// ── Mutations ──────────────────────────────────────────────────────────────

export async function createDocument(
  data: DocumentCreateData
): Promise<{ id: string; status: string; estimated_chunks: number }> {
  return apiFetch("documents", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateMetadata(
  id: string,
  data: DocumentUpdateData
): Promise<void> {
  await apiFetch(`documents/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function updateContent(
  id: string,
  content: string,
  opts?: { source_url?: string; image_urls?: string[]; language?: string }
): Promise<{ status: string; estimated_chunks: number }> {
  return apiFetch(`documents/${id}/content`, {
    method: "POST",
    body: JSON.stringify({ content, ...opts }),
  });
}

export async function deleteDocument(id: string): Promise<void> {
  await apiFetch(`documents/${id}`, { method: "DELETE" });
}

export async function togglePublish(id: string): Promise<{ is_published: boolean }> {
  return apiFetch(`documents/${id}/publish`, { method: "PATCH" });
}

export async function buildIndex(): Promise<void> {
  await apiFetch("index", { method: "POST" });
}

export async function searchTest(
  q: string,
  limit = 5
): Promise<{ query: string; result: string }> {
  return apiFetch(`search?q=${encodeURIComponent(q)}&limit=${limit}`);
}
