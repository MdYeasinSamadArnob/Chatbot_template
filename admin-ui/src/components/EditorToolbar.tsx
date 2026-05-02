"use client";

import { useRef, useState } from "react";
import { Editor } from "@tiptap/react";
import { toYouTubeEmbedUrl } from "@/lib/video-utils";

interface ToolbarProps {
  editor: Editor | null;
}

function Btn({
  active,
  onClick,
  title,
  children,
  disabled,
}: {
  active?: boolean;
  onClick: () => void;
  title: string;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      onMouseDown={(e) => {
        e.preventDefault(); // prevent editor losing focus
        onClick();
      }}
      title={title}
      disabled={disabled}
      className={`px-2.5 py-1.5 rounded text-xs font-semibold transition-colors select-none ${
        active
          ? "bg-blue-600 text-white shadow-sm"
          : "text-gray-600 hover:bg-gray-200 hover:text-gray-900"
      } disabled:opacity-30`}
    >
      {children}
    </button>
  );
}

function Separator() {
  return <div className="w-px h-5 bg-gray-300 mx-1 self-center" />;
}

export function EditorToolbar({ editor }: ToolbarProps) {
  // ── Image modal state ──────────────────────────────────────────────────
  const [imgOpen, setImgOpen] = useState(false);
  const [imgTab, setImgTab] = useState<"url" | "upload">("url");
  const [imgUrl, setImgUrl] = useState("");
  const [imgAlt, setImgAlt] = useState("");
  const [imgWidth, setImgWidth] = useState("100%");
  const [uploading, setUploading] = useState(false);
  const [uploadErr, setUploadErr] = useState("");
  const [chosenFile, setChosenFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  if (!editor) return null;

  const IMG_WIDTHS: [string, string][] = [
    ["25%", "¼"],
    ["50%", "½"],
    ["75%", "¾"],
    ["100%", "Full"],
  ];

  // ── Image modal handlers ───────────────────────────────────────────────
  const openImgModal = () => {
    setImgUrl("");
    setImgAlt("");
    setImgWidth("100%");
    setUploadErr("");
    setChosenFile(null);
    setImgOpen(true);
  };

  const closeImgModal = () => {
    setImgOpen(false);
    setUploading(false);
    setUploadErr("");
  };

  const insertUrl = () => {
    const src = imgUrl.trim();
    if (!src) return;
    editor.chain().focus().setImage({ src, alt: imgAlt, width: imgWidth } as never).run();
    closeImgModal();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setUploadErr("");
    setChosenFile(e.target.files?.[0] ?? null);
  };

  const uploadAndInsert = async () => {
    if (!chosenFile) return;
    setUploading(true);
    setUploadErr("");
    try {
      const form = new FormData();
      form.append("file", chosenFile);
      const res = await fetch("/api/upload", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) {
        setUploadErr(data?.detail ?? `Upload failed (${res.status})`);
        return;
      }
      // Build absolute URL using the public env var so the image renders in bot-ui
      const base = process.env.NEXT_PUBLIC_ADMIN_API_URL ?? "";
      editor.chain().focus().setImage({ src: `${base}${data.url}`, alt: imgAlt, width: imgWidth } as never).run();
      closeImgModal();
    } catch (err) {
      setUploadErr("Network error — could not upload file.");
    } finally {
      setUploading(false);
    }
  };

  // ── Image resize for already-inserted images ───────────────────────────
  const isImageSelected = editor.isActive("image");
  const setSelectedWidth = (w: string) => {
    editor.chain().focus().updateAttributes("image", { width: w }).run();
  };

  // ── Link modal state ──────────────────────────────────────────────────
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");

  const openLinkModal = () => {
    const prev = editor.getAttributes("link").href as string | undefined;
    setLinkUrl(prev ?? "");
    setLinkOpen(true);
  };
  const closeLinkModal = () => setLinkOpen(false);
  const applyLink = () => {
    if (linkUrl.trim() === "") {
      editor.chain().focus().unsetLink().run();
    } else {
      editor.chain().focus().setLink({ href: linkUrl.trim(), target: "_blank" }).run();
    }
    closeLinkModal();
  };
  const removeLink = () => {
    editor.chain().focus().unsetLink().run();
    closeLinkModal();
  };

  // ── YouTube modal state ───────────────────────────────────────────────
  const [ytOpen, setYtOpen] = useState(false);
  const [ytUrl, setYtUrl] = useState("");
  const [ytErr, setYtErr] = useState("");
  const [ytTitle, setYtTitle] = useState("");

  const openYtModal = () => { setYtUrl(""); setYtErr(""); setYtTitle(""); setYtOpen(true); };
  const closeYtModal = () => setYtOpen(false);
  const applyYouTube = () => {
    const embedUrl = toYouTubeEmbedUrl(ytUrl.trim());
    if (!embedUrl) {
      setYtErr("Invalid YouTube URL. Use a youtube.com or youtu.be link.");
      return;
    }
    editor.chain().focus().setYoutubeVideo({ src: embedUrl }).run();
    // Insert a caption paragraph so the LLM can understand the video content
    if (ytTitle.trim()) {
      editor.commands.insertContent(`<p><em>\u{1F4F9} ${ytTitle.trim()}</em></p>`);
    }
    closeYtModal();
  };

  // ── Other handlers ─────────────────────────────────────────────────────
  const insertTable = () =>
    editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();

  return (
    <>
      <div className="flex flex-wrap items-center gap-0.5 border-b border-gray-200 px-2 py-1.5 bg-gray-50 shrink-0">
        {/* Text style */}
        <Btn active={editor.isActive("bold")} onClick={() => editor.chain().focus().toggleBold().run()} title="Bold (Ctrl+B)">
          <strong>B</strong>
        </Btn>
        <Btn active={editor.isActive("italic")} onClick={() => editor.chain().focus().toggleItalic().run()} title="Italic (Ctrl+I)">
          <em>I</em>
        </Btn>
        <Btn active={editor.isActive("strike")} onClick={() => editor.chain().focus().toggleStrike().run()} title="Strikethrough">
          <s>S</s>
        </Btn>
        <Btn active={editor.isActive("highlight")} onClick={() => editor.chain().focus().toggleHighlight().run()} title="Highlight">
          🖊
        </Btn>
        <Btn active={editor.isActive("code")} onClick={() => editor.chain().focus().toggleCode().run()} title="Inline Code">
          {"<>"}
        </Btn>

        <Separator />

        {/* Headings */}
        {([1, 2, 3] as const).map((level) => (
          <Btn
            key={level}
            active={editor.isActive("heading", { level })}
            onClick={() => editor.chain().focus().toggleHeading({ level }).run()}
            title={`Heading ${level}`}
          >
            H{level}
          </Btn>
        ))}
        <Btn
          active={editor.isActive("paragraph")}
          onClick={() => editor.chain().focus().setParagraph().run()}
          title="Paragraph"
        >
          ¶
        </Btn>

        <Separator />

        {/* Lists */}
        <Btn active={editor.isActive("bulletList")} onClick={() => editor.chain().focus().toggleBulletList().run()} title="Bullet list">
          ≡ •
        </Btn>
        <Btn active={editor.isActive("orderedList")} onClick={() => editor.chain().focus().toggleOrderedList().run()} title="Numbered list">
          ≡ 1.
        </Btn>

        <Separator />

        {/* Alignment */}
        <Btn active={editor.isActive({ textAlign: "left" })} onClick={() => editor.chain().focus().setTextAlign("left").run()} title="Align left">
          ←
        </Btn>
        <Btn active={editor.isActive({ textAlign: "center" })} onClick={() => editor.chain().focus().setTextAlign("center").run()} title="Align centre">
          ↔
        </Btn>
        <Btn active={editor.isActive({ textAlign: "right" })} onClick={() => editor.chain().focus().setTextAlign("right").run()} title="Align right">
          →
        </Btn>

        <Separator />

        {/* Blocks */}
        <Btn active={editor.isActive("blockquote")} onClick={() => editor.chain().focus().toggleBlockquote().run()} title="Callout / Blockquote">
          ❝❞
        </Btn>
        <Btn active={editor.isActive("codeBlock")} onClick={() => editor.chain().focus().toggleCodeBlock().run()} title="Code block">
          {"{ }"}
        </Btn>
        <Btn active={false} onClick={() => editor.chain().focus().setHorizontalRule().run()} title="Divider">
          —
        </Btn>

        <Separator />

        {/* Media */}
        <Btn active={editor.isActive("link")} onClick={openLinkModal} title="Link">
          🔗
        </Btn>
        <Btn active={false} onClick={openImgModal} title="Insert image">
          🖼
        </Btn>
        <Btn active={false} onClick={openYtModal} title="Insert YouTube video">
          ▶
        </Btn>
        <Btn active={false} onClick={insertTable} title="Insert table">
          ⊞
        </Btn>

        <Separator />

        {/* Undo / Redo */}
        <Btn active={false} onClick={() => editor.chain().focus().undo().run()} title="Undo (Ctrl+Z)" disabled={!editor.can().undo()}>
          ↩
        </Btn>
        <Btn active={false} onClick={() => editor.chain().focus().redo().run()} title="Redo (Ctrl+Y)" disabled={!editor.can().redo()}>
          ↪
        </Btn>
      </div>

      {/* ── Image resize bar (visible when an image node is selected) ── */}
      {isImageSelected && (
        <div className="flex items-center gap-1.5 px-3 py-1 bg-blue-50 border-b border-blue-200 text-xs">
          <span className="text-blue-700 font-semibold mr-1">🖼 Size:</span>
          {IMG_WIDTHS.map(([w, label]) => (
            <button
              key={w}
              onMouseDown={(e) => { e.preventDefault(); setSelectedWidth(w); }}
              className={`px-2.5 py-1 rounded font-semibold transition-colors ${
                editor.getAttributes("image").width === w
                  ? "bg-blue-600 text-white"
                  : "bg-white border border-blue-300 text-blue-700 hover:bg-blue-100"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {/* ── Image Insert Modal ─────────────────────────────────────────── */}
      {imgOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onMouseDown={(e) => { if (e.target === e.currentTarget) closeImgModal(); }}
        >
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
              <h2 className="text-sm font-semibold text-gray-800">Insert Image</h2>
              <button
                onClick={closeImgModal}
                className="text-gray-400 hover:text-gray-600 text-lg leading-none"
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            {/* Tabs */}
            <div className="flex border-b border-gray-200">
              {(["url", "upload"] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => { setImgTab(tab); setUploadErr(""); }}
                  className={`flex-1 py-2.5 text-xs font-semibold transition-colors ${
                    imgTab === tab
                      ? "border-b-2 border-blue-600 text-blue-700"
                      : "text-gray-500 hover:text-gray-800"
                  }`}
                >
                  {tab === "url" ? "Paste URL" : "Upload File"}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div className="px-5 py-5 space-y-4">
              {imgTab === "url" ? (
                <>
                  <input
                    type="url"
                    placeholder="https://example.com/image.jpg"
                    value={imgUrl}
                    onChange={(e) => setImgUrl(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") insertUrl(); }}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    autoFocus
                  />
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1.5">
                      Alt text <span className="font-normal text-gray-400">(helps AI understand the image)</span>
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. Screenshot of the bank statement download page"
                      value={imgAlt}
                      onChange={(e) => setImgAlt(e.target.value)}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 mb-1.5">Width</p>
                    <div className="flex gap-2">
                      {IMG_WIDTHS.map(([w, label]) => (
                        <button
                          key={w}
                          type="button"
                          onClick={() => setImgWidth(w)}
                          className={`flex-1 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                            imgWidth === w
                              ? "bg-blue-600 text-white border-blue-600"
                              : "border-gray-300 text-gray-600 hover:bg-gray-100"
                          }`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <button
                    onClick={insertUrl}
                    disabled={!imgUrl.trim()}
                    className="w-full py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-40 transition-colors"
                  >
                    Insert
                  </button>
                </>
              ) : (
                <>
                  {/* Hidden file input */}
                  <input
                    ref={fileRef}
                    type="file"
                    accept="image/jpeg,image/png,image/gif,image/webp"
                    className="hidden"
                    onChange={handleFileChange}
                  />
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => fileRef.current?.click()}
                      className="px-4 py-2 rounded-lg border border-gray-300 text-xs font-semibold text-gray-700 hover:bg-gray-100 transition-colors shrink-0"
                    >
                      Choose File
                    </button>
                    <span className="text-xs text-gray-500 truncate">
                      {chosenFile ? chosenFile.name : "No file chosen"}
                    </span>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1.5">
                      Alt text <span className="font-normal text-gray-400">(helps AI understand the image)</span>
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. Screenshot of the bank statement download page"
                      value={imgAlt}
                      onChange={(e) => setImgAlt(e.target.value)}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 mb-1.5">Width</p>
                    <div className="flex gap-2">
                      {IMG_WIDTHS.map(([w, label]) => (
                        <button
                          key={w}
                          type="button"
                          onClick={() => setImgWidth(w)}
                          className={`flex-1 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                            imgWidth === w
                              ? "bg-blue-600 text-white border-blue-600"
                              : "border-gray-300 text-gray-600 hover:bg-gray-100"
                          }`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                  {uploadErr && (
                    <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{uploadErr}</p>
                  )}
                  <button
                    onClick={uploadAndInsert}
                    disabled={!chosenFile || uploading}
                    className="w-full py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-40 transition-colors flex items-center justify-center gap-2"
                  >
                    {uploading && (
                      <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                      </svg>
                    )}
                    {uploading ? "Uploading…" : "Upload & Insert"}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
      {/* ── Link Modal ────────────────────────────────────────────────── */}
      {linkOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onMouseDown={(e) => { if (e.target === e.currentTarget) closeLinkModal(); }}
        >
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm mx-4 overflow-hidden">
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
              <h2 className="text-sm font-semibold text-gray-800">🔗 Insert Link</h2>
              <button onClick={closeLinkModal} className="text-gray-400 hover:text-gray-600 text-lg leading-none" aria-label="Close">✕</button>
            </div>
            <div className="px-5 py-5 space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1.5">URL</label>
                <input
                  type="url"
                  placeholder="https://example.com"
                  value={linkUrl}
                  autoFocus
                  onChange={(e) => setLinkUrl(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") applyLink(); }}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div className="flex gap-2">
                <button
                  onClick={applyLink}
                  className="flex-1 py-2 rounded-lg bg-blue-700 text-white text-sm font-semibold hover:bg-blue-800 transition-colors"
                >
                  {linkUrl.trim() ? "Apply" : "Remove"}
                </button>
                {editor.isActive("link") && (
                  <button
                    onClick={removeLink}
                    className="px-4 py-2 rounded-lg border border-red-300 text-red-600 text-sm font-semibold hover:bg-red-50 transition-colors"
                  >
                    Unlink
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── YouTube Modal ─────────────────────────────────────────────── */}
      {ytOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onMouseDown={(e) => { if (e.target === e.currentTarget) closeYtModal(); }}
        >
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm mx-4 overflow-hidden">
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
              <h2 className="text-sm font-semibold text-gray-800">▶ Insert YouTube Video</h2>
              <button onClick={closeYtModal} className="text-gray-400 hover:text-gray-600 text-lg leading-none" aria-label="Close">✕</button>
            </div>
            <div className="px-5 py-5 space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1.5">YouTube URL</label>
                <input
                  type="url"
                  placeholder="https://youtube.com/watch?v=..."
                  value={ytUrl}
                  autoFocus
                  onChange={(e) => { setYtUrl(e.target.value); setYtErr(""); }}
                  onKeyDown={(e) => { if (e.key === "Enter") applyYouTube(); }}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                {ytErr && <p className="mt-2 text-xs text-red-600 bg-red-50 rounded px-3 py-2">{ytErr}</p>}
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1.5">
                  Caption / description <span className="font-normal text-gray-400">(helps AI understand the video)</span>
                </label>
                <input
                  type="text"
                  placeholder="e.g. How to download your bank statement (step-by-step)"
                  value={ytTitle}
                  onChange={(e) => setYtTitle(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") applyYouTube(); }}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <button
                onClick={applyYouTube}
                disabled={!ytUrl.trim()}
                className="w-full py-2 rounded-lg bg-blue-700 text-white text-sm font-semibold hover:bg-blue-800 disabled:opacity-40 transition-colors"
              >
                Insert Video
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
