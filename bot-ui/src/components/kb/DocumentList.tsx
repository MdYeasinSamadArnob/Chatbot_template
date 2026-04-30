"use client";

import { useState } from "react";
import {
  KBDocument,
  deleteDocument,
  togglePublish,
  useCategories,
  useDocuments,
  useStats,
} from "@/hooks/useKnowledgeBase";

// ── Status badge ───────────────────────────────────────────────────────────

function EmbeddingBadge({ status }: { status: KBDocument["embedding_status"] }) {
  const map: Record<string, { label: string; className: string }> = {
    ready:      { label: "● Ready",       className: "text-green-600 bg-green-50" },
    processing: { label: "◌ Processing…", className: "text-yellow-600 bg-yellow-50 animate-pulse" },
    failed:     { label: "✕ Failed",      className: "text-red-600 bg-red-50" },
    pending:    { label: "○ Pending",     className: "text-gray-500 bg-gray-100" },
  };
  const { label, className } = map[status] ?? map.pending;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${className}`}>
      {label}
    </span>
  );
}

// ── Relative time ──────────────────────────────────────────────────────────

function relativeTime(iso: string | undefined): string {
  if (!iso) return "—";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ── Props ──────────────────────────────────────────────────────────────────

interface DocumentListProps {
  onEdit: (doc: KBDocument | null) => void;
}

// ── Component ─────────────────────────────────────────────────────────────

export default function DocumentList({ onEdit }: DocumentListProps) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [publishedOnly, setPublishedOnly] = useState(false);
  const [page, setPage] = useState(0);
  const LIMIT = 25;

  const { items, total, loading, error, refetch } = useDocuments({
    search: search || undefined,
    category: category || undefined,
    published: publishedOnly || undefined,
    limit: LIMIT,
    offset: page * LIMIT,
  });
  const { stats } = useStats();
  const categories = useCategories();

  const handleDelete = async (doc: KBDocument) => {
    if (!confirm(`Delete "${doc.title}"? This cannot be undone.`)) return;
    try {
      await deleteDocument(doc.id);
      refetch();
    } catch (e) {
      alert(`Delete failed: ${e instanceof Error ? e.message : e}`);
    }
  };

  const handleTogglePublish = async (doc: KBDocument) => {
    try {
      await togglePublish(doc.id);
      refetch();
    } catch (e) {
      alert(`Failed: ${e instanceof Error ? e.message : e}`);
    }
  };

  const totalPages = Math.ceil(total / LIMIT);

  return (
    <div className="space-y-4">
      {/* Stats bar */}
      {stats && (
        <div className="flex gap-6 text-sm text-gray-500 bg-gray-50 rounded-lg px-4 py-2.5">
          <span><span className="font-semibold text-gray-800">{stats.documents}</span> articles</span>
          <span><span className="font-semibold text-gray-800">{stats.chunks}</span> chunks</span>
          <span><span className="font-semibold text-gray-800">{stats.published}</span> published</span>
          <span><span className="font-semibold text-gray-800">{stats.categories}</span> categories</span>
        </div>
      )}

      {/* Filters + New button */}
      <div className="flex flex-wrap gap-3 items-center">
        <input
          type="text"
          placeholder="Search title…"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(0); }}
          className="border border-gray-300 rounded-md px-3 py-1.5 text-sm flex-1 min-w-[180px] focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <select
          value={category}
          onChange={(e) => { setCategory(e.target.value); setPage(0); }}
          className="border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={publishedOnly}
            onChange={(e) => { setPublishedOnly(e.target.checked); setPage(0); }}
            className="rounded"
          />
          Published only
        </label>
        <button
          onClick={() => onEdit(null)}
          className="ml-auto bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-1.5 rounded-md transition-colors"
        >
          + New Article
        </button>
      </div>

      {/* Error state */}
      {error && (
        <div className="text-red-600 bg-red-50 border border-red-200 rounded-md px-4 py-2 text-sm">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Title</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Category</th>
              <th className="px-4 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider">Chunks</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Embedding</th>
              <th className="px-4 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider">Published</th>
              <th className="px-4 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {loading && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-400">Loading…</td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center">
                  <div className="text-gray-400 text-base">No articles found</div>
                  <button
                    onClick={() => onEdit(null)}
                    className="mt-3 text-blue-600 hover:underline text-sm"
                  >
                    Create your first article →
                  </button>
                </td>
              </tr>
            )}
            {!loading && items.map((doc) => (
              <tr key={doc.id} className="hover:bg-gray-50 transition-colors">
                <td className="px-4 py-3 font-medium text-gray-900 max-w-xs truncate">
                  {doc.title}
                </td>
                <td className="px-4 py-3">
                  <span className="inline-flex px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700">
                    {doc.category}
                  </span>
                  {doc.subcategory && (
                    <span className="ml-1 text-gray-400 text-xs">{doc.subcategory}</span>
                  )}
                </td>
                <td className="px-4 py-3 text-center text-gray-600">{doc.chunk_count}</td>
                <td className="px-4 py-3">
                  <EmbeddingBadge status={doc.embedding_status} />
                  {doc.embedded_at && (
                    <div className="text-xs text-gray-400 mt-0.5">
                      {relativeTime(doc.embedded_at)}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 text-center">
                  <button
                    onClick={() => handleTogglePublish(doc)}
                    title={doc.is_published ? "Click to unpublish" : "Click to publish"}
                    className={`w-10 h-5 rounded-full transition-colors focus:outline-none ${
                      doc.is_published ? "bg-green-500" : "bg-gray-300"
                    }`}
                  >
                    <span
                      className={`block w-4 h-4 rounded-full bg-white shadow transition-transform mx-0.5 ${
                        doc.is_published ? "translate-x-5" : "translate-x-0"
                      }`}
                    />
                  </button>
                </td>
                <td className="px-4 py-3 text-center">
                  <div className="flex items-center justify-center gap-2">
                    <button
                      onClick={() => onEdit(doc)}
                      className="text-blue-600 hover:text-blue-800 text-xs font-medium px-2 py-1 rounded hover:bg-blue-50"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(doc)}
                      className="text-red-500 hover:text-red-700 text-xs font-medium px-2 py-1 rounded hover:bg-red-50"
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>{total} total</span>
          <div className="flex gap-2">
            <button
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              className="px-3 py-1 rounded border disabled:opacity-40 hover:bg-gray-100"
            >
              ← Prev
            </button>
            <span className="px-3 py-1">{page + 1} / {totalPages}</span>
            <button
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => p + 1)}
              className="px-3 py-1 rounded border disabled:opacity-40 hover:bg-gray-100"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
