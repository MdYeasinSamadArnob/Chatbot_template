"use client";

import { Editor } from "@tiptap/react";

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
  if (!editor) return null;

  const addImage = () => {
    const url = window.prompt("Image URL:");
    if (url?.trim()) editor.chain().focus().setImage({ src: url.trim() }).run();
  };

  const addLink = () => {
    const prev = editor.getAttributes("link").href as string | undefined;
    const url = window.prompt("Link URL:", prev ?? "https://");
    if (url === null) return;
    if (url.trim() === "") {
      editor.chain().focus().unsetLink().run();
    } else {
      editor.chain().focus().setLink({ href: url.trim(), target: "_blank" }).run();
    }
  };

  const insertTable = () =>
    editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();

  return (
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
        " "
      </Btn>
      <Btn active={editor.isActive("codeBlock")} onClick={() => editor.chain().focus().toggleCodeBlock().run()} title="Code block">
        {"{ }"}
      </Btn>
      <Btn active={false} onClick={() => editor.chain().focus().setHorizontalRule().run()} title="Divider">
        —
      </Btn>

      <Separator />

      {/* Media */}
      <Btn active={editor.isActive("link")} onClick={addLink} title="Link">
        🔗
      </Btn>
      <Btn active={false} onClick={addImage} title="Insert image by URL">
        🖼
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
  );
}
