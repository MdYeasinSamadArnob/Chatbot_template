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

  const editorRef = useRef<EditorPaneRef>(null);

  // ── Load document list ─────────────────────────────────────────────

  const fetchDocuments = useCallback(async () => {
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
    editorRef.current?.clear();
  };

  // ── Load existing document into editor ─────────────────────────────

  const handleSelectDocument = async (doc: KBDocument) => {
    try {
      const res = await fetch(`/api/documents/${doc.id}`);
      if (!res.ok) throw new Error(await res.text());
      const full: KBDocument = await res.json();

      setSelectedId(full.id);
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
    <div className="flex h-screen overflow-hidden bg-gray-100">
      <Toaster position="top-right" />

      {/* ── Left: History sidebar ── */}
      <HistorySidebar
        documents={documents}
        selectedId={selectedId}
        isLoading={isLoading}
        onSelect={handleSelectDocument}
        onNew={handleNew}
        onDelete={handleDelete}
      />

      {/* ── Centre + Right: editor + preview ── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

        {/* ── Top metadata bar ── */}
        <header className="bg-white border-b border-gray-200 px-4 py-2.5 flex flex-wrap items-center gap-2 shrink-0">

          {/* Title */}
          <input
            type="text"
            value={meta.title}
            onChange={(e) => { setMeta((m) => ({ ...m, title: e.target.value })); setIsDirty(true); }}
            placeholder="Document title…"
            className="flex-1 min-w-48 border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-medium"
          />

          {/* Category */}
          <select
            value={meta.category}
            onChange={(e) => setMeta((m) => ({ ...m, category: e.target.value }))}
            className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>
            ))}
          </select>

          {/* Type */}
          <select
            value={meta.document_type}
            onChange={(e) => setMeta((m) => ({ ...m, document_type: e.target.value }))}
            className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {DOC_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>

          {/* Language */}
          <select
            value={meta.language}
            onChange={(e) => setMeta((m) => ({ ...m, language: e.target.value }))}
            className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {LANGUAGES.map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>

          {/* Intent tags */}
          <input
            type="text"
            value={tagsInput}
            onChange={(e) => { setTagsInput(e.target.value); setIsDirty(true); }}
            placeholder="Intent tags (comma separated)"
            className="w-52 border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />

          {/* Author */}
          <input
            type="text"
            value={meta.author}
            onChange={(e) => setMeta((m) => ({ ...m, author: e.target.value }))}
            placeholder="Author"
            className="w-28 border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />

          {/* Published toggle */}
          <label className="flex items-center gap-1.5 text-sm text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              checked={meta.is_published}
              onChange={(e) => setMeta((m) => ({ ...m, is_published: e.target.checked }))}
              className="rounded"
            />
            Published
          </label>

          {/* Dirty indicator */}
          {isDirty && (
            <span className="text-xs text-amber-500 font-medium">● Unsaved</span>
          )}

          {/* Doc ID badge */}
          {selectedId && (
            <span
              className="text-[10px] text-gray-400 font-mono hidden lg:block truncate max-w-[120px]"
              title={selectedId}
            >
              {selectedId.slice(0, 8)}…
            </span>
          )}

          {/* Save button */}
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="ml-auto px-5 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white text-sm font-semibold rounded-lg transition-colors flex items-center gap-1.5 shrink-0"
          >
            {isSaving ? (
              <>
                <span className="animate-spin">⏳</span> Saving…
              </>
            ) : (
              <>💾 {selectedId ? "Save" : "Create"}</>
            )}
          </button>
        </header>

        {/* ── Editor + Preview split pane ── */}
        <div className="flex-1 flex gap-0 overflow-hidden">

          {/* WYSIWYG Editor */}
          <div className="flex-1 min-w-0 bg-white border-r border-gray-200 flex flex-col overflow-hidden">
            <div className="px-4 py-1.5 bg-gray-50 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide shrink-0">
              ✏️ Editor
            </div>
            <div className="flex-1 overflow-hidden">
              <EditorPane ref={editorRef} onChange={handleEditorChange} />
            </div>
          </div>

          {/* Live Preview */}
          <div className="flex-1 min-w-0 bg-white flex flex-col overflow-hidden">
            <div className="px-4 py-1.5 bg-gray-50 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wide shrink-0 flex items-center justify-between">
              <span>👁 Preview (render_blocks)</span>
              <span className="text-gray-400 normal-case font-normal">
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
