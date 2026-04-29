"use client";

import type {
  SourceBlocksMessage as SourceBlocksMessageType,
  SourceRenderBlock,
} from "@/store/types";

interface Props {
  message: SourceBlocksMessageType;
}

function renderBlock(block: SourceRenderBlock, key: string) {
  switch (block.type) {
    case "heading": {
      const Tag = `h${block.level}` as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
      return <Tag key={key} className="font-semibold text-slate-800 mt-2">{block.content}</Tag>;
    }
    case "text":
      return <p key={key} className="text-sm text-slate-700 leading-relaxed">{block.content}</p>;
    case "list": {
      const ordered = block.variant === "ordered";
      const ListTag = ordered ? "ol" : "ul";
      return (
        <ListTag key={key} className={`text-sm text-slate-700 pl-5 ${ordered ? "list-decimal" : "list-disc"}`}>
          {(block.items || []).map((item, i) => (
            <li key={`${key}-${i}`}>{item}</li>
          ))}
        </ListTag>
      );
    }
    case "image":
      return (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={key}
          src={block.url}
          alt={block.alt ?? ""}
          loading="lazy"
          className="rounded-lg border border-slate-200 max-h-72 object-contain"
        />
      );
    case "video":
      return (
        <div key={key} className="relative w-full overflow-hidden rounded-lg border border-slate-200 bg-black" style={{ paddingTop: "56.25%" }}>
          <iframe
            src={block.url}
            title={block.title ?? "YouTube video"}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
            allowFullScreen
            className="absolute left-0 top-0 h-full w-full"
          />
        </div>
      );
    case "callout": {
      const variant = block.variant ?? "info";
      const style: Record<string, string> = {
        info: "bg-blue-50 border-blue-200 text-blue-800",
        warning: "bg-amber-50 border-amber-200 text-amber-800",
        error: "bg-red-50 border-red-200 text-red-800",
        success: "bg-green-50 border-green-200 text-green-800",
        tip: "bg-violet-50 border-violet-200 text-violet-800",
      };
      return <div key={key} className={`rounded-md border px-3 py-2 text-sm ${style[variant] ?? style.info}`}>{block.content}</div>;
    }
    case "code":
      return <pre key={key} className="bg-slate-900 text-slate-100 rounded-lg p-3 text-xs overflow-x-auto"><code>{block.content}</code></pre>;
    case "table":
      return (
        <div key={key} className="overflow-x-auto border border-slate-200 rounded-lg">
          <table className="min-w-full text-xs">
            {Array.isArray(block.headers) && block.headers.length > 0 && (
              <thead className="bg-slate-50">
                <tr>{block.headers.map((h, i) => <th key={`${key}-h-${i}`} className="px-2 py-1 text-left">{h}</th>)}</tr>
              </thead>
            )}
            <tbody>
              {(block.rows || []).map((row, ri) => (
                <tr key={`${key}-r-${ri}`} className="border-t border-slate-100">
                  {row.map((cell, ci) => <td key={`${key}-c-${ri}-${ci}`} className="px-2 py-1">{cell}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "divider":
      return <hr key={key} className="border-slate-200" />;
    default:
      return null;
  }
}

export function SourceBlocksMessage({ message }: Props) {
  if (!message.sources?.length) return null;

  return (
    <div className="px-4 py-2">
      <div className="ml-10 max-w-[88%] md:max-w-[72%] xl:max-w-[680px] rounded-2xl border border-slate-200 bg-slate-50 p-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Sources</p>
        <div className="mt-2 space-y-2">
          {message.sources.map((source, idx) => {
            const title = source.document_title || `Source ${idx + 1}`;
            const blocks = Array.isArray(source.render_blocks) ? source.render_blocks : [];
            return (
              <details key={source.id || String(idx)} className="rounded-lg border border-slate-200 bg-white">
                <summary className="cursor-pointer list-none px-3 py-2 text-sm font-medium text-slate-800 flex items-center justify-between">
                  <span>{title}</span>
                  <span className="text-xs text-slate-500">Expand</span>
                </summary>
                <div className="px-3 pb-3 space-y-2">
                  {blocks.length > 0 ? (
                    blocks.map((block, bi) => renderBlock(block, `${source.id || idx}-${bi}`))
                  ) : (
                    <p className="text-sm text-slate-700">{source.content_text || "No structured blocks available."}</p>
                  )}
                  {source.source_url && (
                    <a
                      href={source.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-block text-xs text-[#1A56DB] underline"
                    >
                      Open source
                    </a>
                  )}
                </div>
              </details>
            );
          })}
        </div>
      </div>
    </div>
  );
}
