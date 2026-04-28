"use client";

import type { KBDocument } from "@/types";

const CATEGORY_ICONS: Record<string, string> = {
  general:  "🌐",
  account:  "🏦",
  transfer: "↔️",
  loan:     "💰",
  card:     "💳",
};

const TYPE_BADGES: Record<string, string> = {
  faq:       "bg-blue-100 text-blue-700",
  procedure: "bg-purple-100 text-purple-700",
  policy:    "bg-orange-100 text-orange-700",
  scraped:   "bg-gray-100 text-gray-600",
};

const EMBEDDING_BADGES: Record<string, string> = {
  ready: "bg-emerald-100 text-emerald-700",
  processing: "bg-amber-100 text-amber-700",
  failed: "bg-rose-100 text-rose-700",
  pending: "bg-slate-200 text-slate-600",
};

interface Props {
  documents: KBDocument[];
  selectedId: string | null;
  isLoading: boolean;
  onSelect: (doc: KBDocument) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export function HistorySidebar({
  documents,
  selectedId,
  isLoading,
  onSelect,
  onNew,
  onDelete,
}: Props) {
  return (
    <aside className="flex h-full w-full max-w-[22rem] shrink-0 flex-col bg-gray-900 text-white lg:w-72 lg:max-w-none">
      {/* Header */}
      <div className="px-4 py-4 border-b border-gray-700/60">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-lg">📚</span>
          <h1 className="text-sm font-semibold text-gray-200 tracking-wide uppercase">
            KB Editor
          </h1>
        </div>
        <button
          onClick={onNew}
          className="w-full rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium transition-colors hover:bg-blue-500 flex items-center justify-center gap-1.5"
        >
          <span className="text-lg leading-none">+</span> New Document
        </button>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
        {isLoading ? (
          <div className="text-gray-500 text-xs text-center py-6">
            Loading…
          </div>
        ) : documents.length === 0 ? (
          <div className="text-gray-600 text-xs text-center py-6 px-2">
            No documents yet.
            <br />
            Click <strong>New Document</strong> to start.
          </div>
        ) : (
          documents.map((doc) => (
            <div
              key={doc.id}
              onClick={() => onSelect(doc)}
              className={`group relative cursor-pointer rounded-lg p-3 transition-colors ${
                selectedId === doc.id
                  ? "bg-blue-700 text-white"
                  : "hover:bg-gray-800 text-gray-300"
              }`}
            >
              {/* Top row: icon + type badge */}
              <div className="flex items-center gap-1.5 mb-1">
                <span className="text-xs">
                  {CATEGORY_ICONS[doc.category] ?? "📄"}
                </span>
                <span
                  className={`text-[10px] font-semibold px-1.5 py-0.5 rounded uppercase tracking-wide ${
                    TYPE_BADGES[doc.document_type ?? "faq"] ?? TYPE_BADGES.faq
                  }`}
                >
                  {doc.document_type ?? "faq"}
                </span>
              </div>

              {/* Title */}
              <p className="text-sm font-medium leading-snug line-clamp-2">
                {doc.title}
              </p>

              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px]">
                <span className={`rounded-full px-2 py-0.5 font-semibold uppercase tracking-wide ${doc.is_published ? "bg-emerald-500/15 text-emerald-300" : "bg-slate-500/20 text-slate-300"}`}>
                  {doc.is_published ? "Published" : "Draft"}
                </span>
                <span className={`rounded-full px-2 py-0.5 font-semibold ${EMBEDDING_BADGES[doc.embedding_status ?? "pending"] ?? EMBEDDING_BADGES.pending}`}>
                  {doc.embedding_status ?? "pending"}
                </span>
                {doc.subcategory && (
                  <span className="rounded-full bg-white/10 px-2 py-0.5 text-gray-200">
                    {doc.subcategory}
                  </span>
                )}
              </div>

              {/* Date + version */}
              <p className="mt-2 text-[10px] text-gray-500">
                {new Date(doc.updated_at).toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                })}{" "}
                · v{doc.version}
              </p>

              {/* Delete button (hover only) */}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(doc.id);
                }}
                title="Delete document"
                className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400 text-xs transition-opacity p-1"
              >
                ✕
              </button>
            </div>
          ))
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-gray-700/60 px-4 py-2 text-center text-[10px] text-gray-600">
        {documents.length} document{documents.length !== 1 ? "s" : ""}
      </div>
    </aside>
  );
}
