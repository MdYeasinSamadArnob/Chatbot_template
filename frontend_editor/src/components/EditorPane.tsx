"use client";

import { forwardRef, useImperativeHandle, useEffect, useRef } from "react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import TextAlign from "@tiptap/extension-text-align";
import Highlight from "@tiptap/extension-highlight";
import Placeholder from "@tiptap/extension-placeholder";
import { EditorToolbar } from "./EditorToolbar";

export interface EditorPaneRef {
  getHTML: () => string;
  setContent: (html: string) => void;
  clear: () => void;
}

interface EditorPaneProps {
  onChange: (html: string) => void;
}

export const EditorPane = forwardRef<EditorPaneRef, EditorPaneProps>(
  ({ onChange }, ref) => {
    const editor = useEditor({
      extensions: [
        StarterKit.configure({
          heading: { levels: [1, 2, 3, 4, 5, 6] },
        }),
        Image.configure({ inline: false, allowBase64: false }),
        Link.configure({ openOnClick: false, autolink: true }),
        Table.configure({ resizable: false }),
        TableRow,
        TableCell,
        TableHeader,
        TextAlign.configure({ types: ["heading", "paragraph"] }),
        Highlight,
        Placeholder.configure({
          placeholder: "Start writing your banking knowledge article…",
        }),
      ],
      content: "",
      immediatelyRender: false,
      onUpdate: ({ editor }) => onChange(editor.getHTML()),
      editorProps: {
        attributes: {
          class:
            "prose prose-sm max-w-none focus:outline-none px-6 py-5 min-h-full",
        },
      },
    });

    // Buffer content requested before TipTap's async init completes
    const pendingContent = useRef<string | null>(null);

    // Apply buffered content as soon as the editor instance is ready
    useEffect(() => {
      if (editor && pendingContent.current !== null) {
        editor.commands.setContent(pendingContent.current, false);
        pendingContent.current = null;
      }
    }, [editor]);

    useImperativeHandle(ref, () => ({
      getHTML: () => editor?.getHTML() ?? "",
      setContent: (html: string) => {
        if (editor) {
          editor.commands.setContent(html, false);
        } else {
          // Editor not yet initialised — buffer and apply once ready
          pendingContent.current = html;
        }
      },
      clear: () => {
        editor?.commands.clearContent(true);
        pendingContent.current = null;
      },
    }), [editor]);

    useEffect(() => () => { editor?.destroy(); }, [editor]);

    return (
      <div className="flex flex-col h-full overflow-hidden">
        <EditorToolbar editor={editor} />
        <div className="flex-1 overflow-y-auto">
          <EditorContent editor={editor} className="h-full" />
        </div>
      </div>
    );
  }
);

EditorPane.displayName = "EditorPane";
