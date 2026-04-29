"use client";

import type { RenderBlock } from "@/types";

interface PreviewPaneProps {
  blocks: RenderBlock[];
  html?: string;
}

export function PreviewPane({ blocks, html = "" }: PreviewPaneProps) {
  if (!html.trim() && blocks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-400 select-none">
        <span className="text-5xl mb-3">📄</span>
        <p className="text-sm">Preview updates as you type</p>
      </div>
    );
  }

  if (html.trim()) {
    return (
      <div className="h-full overflow-y-auto p-6">
        <article
          className="kb-preview prose prose-sm max-w-none prose-slate"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4 overflow-y-auto h-full">
      {blocks.map((block, i) => (
        <Block key={i} block={block} />
      ))}
    </div>
  );
}

function Block({ block }: { block: RenderBlock }) {
  switch (block.type) {
    case "heading": {
      const classes: Record<number, string> = {
        1: "text-3xl font-bold text-gray-900 mt-4",
        2: "text-2xl font-bold text-gray-800 mt-3",
        3: "text-xl font-semibold text-gray-800 mt-2",
        4: "text-lg font-semibold text-gray-700",
        5: "text-base font-semibold text-gray-700",
        6: "text-sm font-semibold text-gray-600 uppercase tracking-wide",
      };
      const Tag = `h${block.level}` as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
      return <Tag className={classes[block.level]}>{block.content}</Tag>;
    }

    case "text":
      return <p className="text-gray-700 leading-relaxed">{block.content}</p>;

    case "list":
      if (block.variant === "ordered") {
        return (
          <ol className="list-decimal list-outside pl-5 space-y-1 text-gray-700">
            {block.items.map((item, i) => (
              <li key={i} className="leading-relaxed">{item}</li>
            ))}
          </ol>
        );
      }
      return (
        <ul className="list-disc list-outside pl-5 space-y-1 text-gray-700">
          {block.items.map((item, i) => (
            <li key={i} className="leading-relaxed">{item}</li>
          ))}
        </ul>
      );

    case "image":
      return (
        <figure className="my-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={block.url}
            alt={block.alt}
            className="rounded-lg max-w-full border border-gray-200 shadow-sm"
          />
          {block.alt && (
            <figcaption className="text-xs text-gray-500 mt-1 text-center">
              {block.alt}
            </figcaption>
          )}
        </figure>
      );

    case "video":
      return (
        <figure className="my-2">
          <div className="relative w-full overflow-hidden rounded-lg border border-gray-200 bg-black shadow-sm" style={{ paddingTop: "56.25%" }}>
            <iframe
              src={block.url}
              title={block.title ?? "YouTube video"}
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
              allowFullScreen
              className="absolute left-0 top-0 h-full w-full"
            />
          </div>
          {block.title && (
            <figcaption className="text-xs text-gray-500 mt-1 text-center">
              {block.title}
            </figcaption>
          )}
        </figure>
      );

    case "callout": {
      const styles: Record<string, string> = {
        info:    "bg-blue-50   border-blue-400   text-blue-800",
        warning: "bg-yellow-50 border-yellow-400 text-yellow-800",
        error:   "bg-red-50    border-red-400    text-red-800",
        success: "bg-green-50  border-green-400  text-green-800",
        tip:     "bg-purple-50 border-purple-400 text-purple-800",
      };
      const icons: Record<string, string> = {
        info: "ℹ️", warning: "⚠️", error: "❌", success: "✅", tip: "💡",
      };
      return (
        <div className={`border-l-4 p-4 rounded-r-lg text-sm ${styles[block.variant] ?? styles.info}`}>
          <span className="mr-2">{icons[block.variant] ?? "·"}</span>
          {block.content}
        </div>
      );
    }

    case "code":
      return (
        <pre className="bg-gray-900 text-green-300 p-4 rounded-lg overflow-x-auto text-sm leading-relaxed">
          <code>{block.content}</code>
        </pre>
      );

    case "table":
      return (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="min-w-full text-sm">
            {block.headers.length > 0 && (
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  {block.headers.map((h, i) => (
                    <th key={i} className="px-4 py-2.5 text-left font-semibold text-gray-700">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {block.rows.map((row, ri) => (
                <tr
                  key={ri}
                  className={ri % 2 === 0 ? "bg-white" : "bg-gray-50"}
                >
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-4 py-2 text-gray-700 border-t border-gray-100">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    case "divider":
      return <hr className="border-gray-200 my-2" />;

    default:
      return null;
  }
}
