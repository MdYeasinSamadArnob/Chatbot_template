"use client";

import { useEffect, useState } from "react";
import {
  KBDocument,
  createDocument,
  updateContent,
  updateMetadata,
  useEmbeddingStatus,
} from "@/hooks/useKnowledgeBase";

// ── Status badge ───────────────────────────────────────────────────────────

function EmbeddingBadge({ status }: { status: string | null }) {
  if (!status) return null;
  const map: Record<string, { label: string; className: string }> = {
    ready:      { label: "● Ready",       className: "text-green-600 bg-green-50 border-green-200" },
    processing: { label: "◌ Embedding…",  className: "text-yellow-600 bg-yellow-50 border-yellow-200 animate-pulse" },
    failed:     { label: "✕ Failed",      className: "text-red-600 bg-red-50 border-red-200" },
    pending:    { label: "○ Pending",     className: "text-gray-500 bg-gray-50 border-gray-200" },
  };
  const { label, className } = map[status] ?? map.pending;
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded border text-xs font-medium ${className}`}>
      {label}
    </span>
  );
}

function relativeTime(iso: string | undefined | null): string {
  if (!iso) return "";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ── Props ──────────────────────────────────────────────────────────────────

interface DocumentEditorProps {
  doc: KBDocument | null;       // null = create new
  onClose: () => void;
  onSaved: () => void;
}

// ── Component ─────────────────────────────────────────────────────────────

export default function DocumentEditor({ doc, onClose, onSaved }: DocumentEditorProps) {
  const isNew = doc === null;

  // Form fields
  const [title, setTitle] = useState(doc?.title ?? "");
  const [category, setCategory] = useState(doc?.category ?? "");
  const [subcategory, setSubcategory] = useState(doc?.subcategory ?? "");
  const [author, setAuthor] = useState(doc?.author ?? "");
  const [intentTagsRaw, setIntentTagsRaw] = useState((doc?.intent_tags ?? []).join(", "));
  const [sourceUrl, setSourceUrl] = useState("");
  const [imageUrlsRaw, setImageUrlsRaw] = useState("");
  const [content, setContent] = useState("");
  const [isPublished, setIsPublished] = useState(doc?.is_published ?? true);

  // Tracking
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedDocId, setSavedDocId] = useState<string | null>(doc?.id ?? null);
  const [estimatedChunks, setEstimatedChunks] = useState<number | null>(null);

  const { status: embStatus, embeddedAt } = useEmbeddingStatus(savedDocId);

  // Reset when doc changes
  useEffect(() => {
    setTitle(doc?.title ?? "");
    setCategory(doc?.category ?? "");
    setSubcategory(doc?.subcategory ?? "");
    setAuthor(doc?.author ?? "");
    setIntentTagsRaw((doc?.intent_tags ?? []).join(", "));
    setIsPublished(doc?.is_published ?? true);
    setContent("");
    setSourceUrl("");
    setImageUrlsRaw("");
    setSavedDocId(doc?.id ?? null);
    setEstimatedChunks(null);
    setError(null);
  }, [doc]);

  const handleSave = async () => {
    if (!title.trim()) { setError("Title is required"); return; }
    if (!category.trim()) { setError("Category is required"); return; }

    setSaving(true);
    setError(null);

    try {
      const intentTags = intentTagsRaw
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const imageUrls = imageUrlsRaw
        .split("\n")
        .map((u) => u.trim())
        .filter(Boolean);

      if (isNew) {
        if (!content.trim()) { setError("Content is required for new articles"); setSaving(false); return; }
        const res = await createDocument({
          title: title.trim(),
          category: category.trim(),
          subcategory: subcategory.trim() || undefined,
          intent_tags: intentTags,
          author: author.trim() || undefined,
          is_published: isPublished,
          content: content.trim(),
          source_url: sourceUrl.trim() || undefined,
          image_urls: imageUrls.length ? imageUrls : undefined,
        });
        setSavedDocId(res.id);
        setEstimatedChunks(res.estimated_chunks);
      } else {
        // Update metadata
        await updateMetadata(doc!.id, {
          title: title.trim(),
          category: category.trim(),
          subcategory: subcategory.trim() || undefined,
          intent_tags: intentTags,
          author: author.trim() || undefined,
          is_published: isPublished,
        });

        // Re-embed if content provided
        if (content.trim()) {
          const res = await updateContent(doc!.id, content.trim(), {
            source_url: sourceUrl.trim() || undefined,
            image_urls: imageUrls.length ? imageUrls : undefined,
          });
          setEstimatedChunks(res.estimated_chunks);
        }
      }
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    /* Overlay */
    <div className="fixed inset-0 z-40 flex">
      {/* Backdrop */}
      <div
        className="flex-1 bg-black/40"
        onClick={onClose}
      />

      {/* Slide-over panel */}
      <div className="w-full max-w-2xl bg-white h-full overflow-y-auto shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">
            {isNew ? "New Article" : "Edit Article"}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-2xl leading-none"
          >
            ×
          </button>
        </div>

        {/* Embedding status (edit mode) */}
        {savedDocId && (
          <div className="px-6 py-3 border-b border-gray-100 bg-gray-50 flex items-center gap-3 text-sm">
            <EmbeddingBadge status={embStatus ?? doc?.embedding_status ?? null} />
            {estimatedChunks != null && embStatus === "processing" && (
              <span className="text-gray-500">~{estimatedChunks} chunks</span>
            )}
            {(embeddedAt || doc?.embedded_at) && embStatus !== "processing" && (
              <span className="text-gray-400">
                Last embedded: {relativeTime(embeddedAt ?? doc?.embedded_at)}
              </span>
            )}
          </div>
        )}

        {/* Form */}
        <div className="flex-1 px-6 py-5 space-y-5">
          {error && (
            <div className="text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2 text-sm">
              {error}
            </div>
          )}

          <Field label="Title *">
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="input-base"
              placeholder="e.g. How to Block a Lost Card"
            />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Category *">
              <input
                type="text"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="input-base"
                placeholder="e.g. Cards"
              />
            </Field>
            <Field label="Subcategory">
              <input
                type="text"
                value={subcategory}
                onChange={(e) => setSubcategory(e.target.value)}
                className="input-base"
                placeholder="Optional"
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Author">
              <input
                type="text"
                value={author}
                onChange={(e) => setAuthor(e.target.value)}
                className="input-base"
                placeholder="Optional"
              />
            </Field>
            <Field label="Intent Tags (comma-separated)">
              <input
                type="text"
                value={intentTagsRaw}
                onChange={(e) => setIntentTagsRaw(e.target.value)}
                className="input-base"
                placeholder="e.g. block_card, lost_card"
              />
            </Field>
          </div>

          <Field label="Source URL">
            <input
              type="url"
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
              className="input-base"
              placeholder="https://help.bank.example/..."
            />
          </Field>

          <Field label="Image URLs (one per line)">
            <textarea
              rows={3}
              value={imageUrlsRaw}
              onChange={(e) => setImageUrlsRaw(e.target.value)}
              className="input-base resize-none font-mono text-xs"
              placeholder={"https://cdn.example.com/step1.png\nhttps://cdn.example.com/step2.png"}
            />
          </Field>

          <Field
            label={isNew ? "Content *" : "Content (leave blank to keep existing)"}
          >
            <textarea
              rows={12}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="input-base resize-y font-mono text-xs"
              placeholder={
                isNew
                  ? "Write article content here. Use ## headings for sections."
                  : "Paste new content to re-embed. Leave blank to keep current chunks."
              }
            />
            {content && (
              <div className="text-xs text-gray-400 mt-1 text-right">
                {content.length.toLocaleString()} chars
              </div>
            )}
          </Field>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="is_published"
              checked={isPublished}
              onChange={(e) => setIsPublished(e.target.checked)}
              className="rounded"
            />
            <label htmlFor="is_published" className="text-sm text-gray-700 cursor-pointer">
              Published (visible to chatbot)
            </label>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-end gap-3 bg-white">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-5 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-md transition-colors"
          >
            {saving ? "Saving…" : isNew ? "Create & Embed" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Small helper ───────────────────────────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="block text-sm font-medium text-gray-700">{label}</label>
      {children}
    </div>
  );
}
