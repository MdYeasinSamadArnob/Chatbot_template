"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import toast, { Toaster } from "react-hot-toast";
import type { KBDocument, DocumentMetadata, RenderBlock } from "@/types";
import { htmlToRenderBlocks, contentToHtml } from "@/lib/html-utils";
import { HistorySidebar } from "@/components/HistorySidebar";
import { PreviewPane } from "@/components/PreviewPane";
import { EditorPane, type EditorPaneRef } from "@/components/EditorPane";

// ── Constants ──────────────────────────────────────────────────────────────

const EMPTY_META: DocumentMetadata = {
  title: "",
  category: "general",
  subcategory: "",
  document_type: "faq",
  content_type: "wysiwyg_html",
  language: "en",
  intent_tags: [],
  author: "",
  is_published: true,
  source_url: "",
  relevance_score: null,
};

const CATEGORIES = ["general", "account", "transfer", "loan", "card"] as const;
const DOC_TYPES  = ["faq", "procedure", "policy", "scraped"] as const;
const LANGUAGES  = ["en", "bn", "mixed"] as const;
const LIST_STATUS_FILTERS = ["all", "published", "draft", "processing", "failed"] as const;

// ── Component ──────────────────────────────────────────────────────────────

export default function EditorPage() {
  const [documents, setDocuments]     = useState<KBDocument[]>([]);
  const [selectedId, setSelectedId]   = useState<string | null>(null);
  const [meta, setMeta]               = useState<DocumentMetadata>({ ...EMPTY_META });
  const [tagsInput, setTagsInput]     = useState("");
  const [blocks, setBlocks]           = useState<RenderBlock[]>([]);
  const [isSaving, setIsSaving]       = useState(false);
  const [isLoading, setIsLoading]     = useState(true);
  const [isDirty, setIsDirty]         = useState(false);
  const [listQuery, setListQuery]     = useState("");
  const [listCategory, setListCategory] = useState("all");
  const [listStatus, setListStatus]   = useState<(typeof LIST_STATUS_FILTERS)[number]>("all");
  const [isDocPanelOpen, setIsDocPanelOpen] = useState(false);
  const [mobilePane, setMobilePane]   = useState<"editor" | "preview">("editor");

  const editorRef = useRef<EditorPaneRef>(null);
  const relevanceInput = meta.relevance_score == null ? "" : String(meta.relevance_score);
  const normalizedQuery = listQuery.trim().toLowerCase();
  const categories = Array.from(new Set(documents.map((doc) => doc.category).filter(Boolean))).sort();
  const filteredDocuments = documents.filter((doc) => {
    const matchesQuery =
      !normalizedQuery ||
      doc.title.toLowerCase().includes(normalizedQuery) ||
      doc.category.toLowerCase().includes(normalizedQuery) ||
      (doc.subcategory ?? "").toLowerCase().includes(normalizedQuery) ||
      (doc.author ?? "").toLowerCase().includes(normalizedQuery);

    const matchesCategory = listCategory === "all" || doc.category === listCategory;

    const matchesStatus =
      listStatus === "all" ||
      (listStatus === "published" && doc.is_published) ||
      (listStatus === "draft" && !doc.is_published) ||
      (listStatus === "processing" && doc.embedding_status === "processing") ||
      (listStatus === "failed" && doc.embedding_status === "failed");

    return matchesQuery && matchesCategory && matchesStatus;
  });
  const publishedCount = documents.filter((doc) => doc.is_published).length;
  const draftCount = documents.length - publishedCount;
  const processingCount = documents.filter((doc) => doc.embedding_status === "processing").length;
  const failedCount = documents.filter((doc) => doc.embedding_status === "failed").length;

  // ── Load document list ─────────────────────────────────────────────

  const fetchDocuments = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await fetch("/api/documents");
      if (!res.ok) throw new Error(await res.text());
      setDocuments(await res.json());
    } catch {
      toast.error("Could not load documents");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { fetchDocuments(); }, [fetchDocuments]);

  // ── Editor change callback ─────────────────────────────────────────

  const handleEditorChange = useCallback((html: string) => {
    setBlocks(htmlToRenderBlocks(html));
    setIsDirty(true);
  }, []);

  // ── New document ───────────────────────────────────────────────────

  const handleNew = () => {
    setSelectedId(null);
    setMeta({ ...EMPTY_META });
    setTagsInput("");
    setBlocks([]);
    setIsDirty(false);
    setMobilePane("editor");
    setIsDocPanelOpen(false);
    editorRef.current?.clear();
  };

  // ── Load existing document into editor ─────────────────────────────

  const handleSelectDocument = async (doc: KBDocument) => {
    try {
      const res = await fetch(`/api/documents/${doc.id}`);
      if (!res.ok) throw new Error(await res.text());
      const full: KBDocument = await res.json();

      setSelectedId(full.id);
      setMobilePane("editor");
      setIsDocPanelOpen(false);
      setMeta({
        title:         full.title            ?? "",
        category:      full.category         ?? "general",
        subcategory:   full.subcategory       ?? "",
        document_type: full.document_type     ?? "faq",
        content_type:  full.content_type      ?? "wysiwyg_html",
        language:      full.language          ?? "en",
        intent_tags:   full.intent_tags       ?? [],
        author:        full.author            ?? "",
        is_published:  full.is_published      ?? true,
        source_url:    full.source_url        ?? "",
        relevance_score: full.relevance_score ?? null,
      });
      setTagsInput((full.intent_tags ?? []).join(", "));

      const html = contentToHtml(full.content_raw ?? "", full.content_type ?? "wysiwyg_html");
      editorRef.current?.setContent(html);
      setBlocks(htmlToRenderBlocks(html));
      setIsDirty(false);
    } catch {
      toast.error("Failed to load document");
    }
  };

  // ── Save (create or update) ────────────────────────────────────────

  const handleSave = async () => {
    if (!meta.title.trim()) {
      toast.error("Title is required");
      return;
    }

    setIsSaving(true);

    const intent_tags = tagsInput
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

    const payload = {
      ...meta,
      intent_tags,
      content_raw: editorRef.current?.getHTML() ?? "",
    };

    try {
      const isNew = !selectedId;
      const url    = isNew ? "/api/documents" : `/api/documents/${selectedId}`;
      const method = isNew ? "POST" : "PUT";

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error ?? "Save failed");
      }

      const saved: KBDocument = await res.json();
      if (isNew) setSelectedId(saved.id);
      setIsDirty(false);
      toast.success(isNew ? "Document created!" : "Document saved!");
      fetchDocuments();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Save failed");
    } finally {
      setIsSaving(false);
    }
  };

  // ── Delete ─────────────────────────────────────────────────────────

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this document? This action soft-deletes the record.")) return;
    try {
      const res = await fetch(`/api/documents/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      if (selectedId === id) handleNew();
      fetchDocuments();
      toast.success("Document deleted");
    } catch {
      toast.error("Delete failed");
    }
  };

  // ── Keyboard shortcut: Ctrl/Cmd + S ───────────────────────────────

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        handleSave();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta, tagsInput, selectedId]);

  // ── Render ─────────────────────────────────────────────────────────

  return (
    <div className="flex h-screen overflow-hidden bg-slate-100">
      <Toaster position="top-right" />

      {isDocPanelOpen && (
        <div className="fixed inset-0 z-40 bg-slate-950/50 lg:hidden" onClick={() => setIsDocPanelOpen(false)}>
          <div className="h-full max-w-[22rem]" onClick={(e) => e.stopPropagation()}>
            <HistorySidebar
              documents={filteredDocuments}
              selectedId={selectedId}
              isLoading={isLoading}
              onSelect={handleSelectDocument}
              onNew={handleNew}
              onDelete={handleDelete}
            />
          </div>
        </div>
      )}

      <div className="hidden lg:flex">
        <HistorySidebar
          documents={filteredDocuments}
          selectedId={selectedId}
          isLoading={isLoading}
          onSelect={handleSelectDocument}
          onNew={handleNew}
          onDelete={handleDelete}
        />
      </div>

      {/* ── Centre + Right: editor + preview ── */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">

        <header className="border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur sm:px-5">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setIsDocPanelOpen(true)}
              className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 lg:hidden"
            >
              Documents
            </button>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                Knowledge Base Editor
              </p>
              <h1 className="truncate text-lg font-semibold text-slate-900 sm:text-xl">
                {meta.title.trim() || (selectedId ? "Untitled document" : "New document")}
              </h1>
            </div>
            <button
              type="button"
              onClick={handleNew}
              className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
            >
              New
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="inline-flex items-center rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 disabled:opacity-60"
            >
              {isSaving ? "Saving..." : selectedId ? "Save" : "Create"}
            </button>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-5">
            <StatCard label="Visible" value={String(filteredDocuments.length)} />
            <StatCard label="Published" value={String(publishedCount)} />
            <StatCard label="Drafts" value={String(draftCount)} />
            <StatCard label="Embedding" value={String(processingCount)} />
            <StatCard label="Failed" value={String(failedCount)} className="col-span-2 sm:col-span-1" />
          </div>

          <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr),180px,180px]">
            <input
              type="text"
              value={listQuery}
              onChange={(e) => setListQuery(e.target.value)}
              placeholder="Search title, category, author..."
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <select
              value={listCategory}
              onChange={(e) => setListCategory(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">All categories</option>
              {categories.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
            <select
              value={listStatus}
              onChange={(e) => setListStatus(e.target.value as (typeof LIST_STATUS_FILTERS)[number])}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">All statuses</option>
              <option value="published">Published</option>
              <option value="draft">Drafts</option>
              <option value="processing">Embedding</option>
              <option value="failed">Failed</option>
            </select>
          </div>
        </header>

        <section className="border-b border-slate-200 bg-slate-50 px-4 py-3 sm:px-5">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <input
              type="text"
              value={meta.title}
              onChange={(e) => { setMeta((m) => ({ ...m, title: e.target.value })); setIsDirty(true); }}
              placeholder="Document title"
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 xl:col-span-2"
            />
            <select
              value={meta.category}
              onChange={(e) => {
                setMeta((m) => ({ ...m, category: e.target.value }));
                setIsDirty(true);
              }}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
              ))}
            </select>
            <input
              type="text"
              value={meta.subcategory}
              onChange={(e) => {
                setMeta((m) => ({ ...m, subcategory: e.target.value }));
                setIsDirty(true);
              }}
              placeholder="Subcategory"
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />

            <select
              value={meta.document_type}
              onChange={(e) => {
                setMeta((m) => ({ ...m, document_type: e.target.value }));
                setIsDirty(true);
              }}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {DOC_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <select
              value={meta.language}
              onChange={(e) => {
                setMeta((m) => ({ ...m, language: e.target.value }));
                setIsDirty(true);
              }}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {LANGUAGES.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
            <input
              type="text"
              value={meta.author}
              onChange={(e) => {
                setMeta((m) => ({ ...m, author: e.target.value }));
                setIsDirty(true);
              }}
              placeholder="Author"
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <input
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={relevanceInput}
              onChange={(e) => {
                const nextValue = e.target.value;
                setMeta((m) => ({
                  ...m,
                  relevance_score: nextValue === "" ? null : Number(nextValue),
                }));
                setIsDirty(true);
              }}
              placeholder="Relevance"
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />

            <input
              type="text"
              value={tagsInput}
              onChange={(e) => { setTagsInput(e.target.value); setIsDirty(true); }}
              placeholder="Intent tags (comma separated)"
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 xl:col-span-2"
            />
            <input
              type="url"
              value={meta.source_url}
              onChange={(e) => {
                setMeta((m) => ({ ...m, source_url: e.target.value }));
                setIsDirty(true);
              }}
              placeholder="Source URL"
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 xl:col-span-2"
            />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-slate-600">
            <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={meta.is_published}
              onChange={(e) => {
                setMeta((m) => ({ ...m, is_published: e.target.checked }));
                setIsDirty(true);
              }}
              className="rounded"
            />
            Published
          </label>

          {isDirty && (
            <span className="text-xs font-medium text-amber-500">● Unsaved</span>
          )}
          {selectedId && (
            <span className="max-w-[160px] truncate font-mono text-[10px] text-slate-400" title={selectedId}>
              {selectedId.slice(0, 8)}…
            </span>
          )}
          </div>
        </section>

        <div className="border-b border-slate-200 bg-white px-4 py-2 lg:hidden">
          <div className="grid grid-cols-2 gap-2 rounded-xl bg-slate-100 p-1">
            <button
              type="button"
              onClick={() => setMobilePane("editor")}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${mobilePane === "editor" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"}`}
            >
              Editor
            </button>
            <button
              type="button"
              onClick={() => setMobilePane("preview")}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${mobilePane === "preview" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"}`}
            >
              Preview
            </button>
          </div>
        </div>

        {/* ── Editor + Preview split pane ── */}
        <div className="flex flex-1 gap-0 overflow-hidden">

          {/* WYSIWYG Editor */}
          <div className={`${mobilePane === "editor" ? "flex" : "hidden"} min-w-0 flex-1 flex-col overflow-hidden bg-white lg:flex lg:border-r lg:border-slate-200`}>
            <div className="shrink-0 border-b border-slate-100 bg-slate-50 px-4 py-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
              ✏️ Editor
            </div>
            <div className="flex-1 overflow-hidden">
              <EditorPane ref={editorRef} onChange={handleEditorChange} />
            </div>
          </div>

          {/* Live Preview */}
          <div className={`${mobilePane === "preview" ? "flex" : "hidden"} min-w-0 flex-1 flex-col overflow-hidden bg-white lg:flex`}>
            <div className="flex shrink-0 items-center justify-between border-b border-slate-100 bg-slate-50 px-4 py-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <span>👁 Preview (render_blocks)</span>
              <span className="normal-case font-normal text-slate-400">
                {blocks.length} block{blocks.length !== 1 ? "s" : ""}
              </span>
            </div>
            <div className="flex-1 overflow-hidden">
              <PreviewPane blocks={blocks} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  className = "",
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className={`rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 ${className}`}>
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-900">{value}</p>
    </div>
  );
}
