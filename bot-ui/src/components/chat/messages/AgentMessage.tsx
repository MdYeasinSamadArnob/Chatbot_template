"use client";

import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Sparkles } from "lucide-react";
import type { AgentTextMessage as AgentTextMessageType } from "@/store/types";

interface Props {
  message: AgentTextMessageType;
}

function formatTime(ts: number) {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

const TOOL_JSON_RE =
  /^\s*\{\s*"(?:type"\s*:\s*"function"|name"\s*:\s*"[a-zA-Z_][a-zA-Z0-9_]*")/;

const KNOWN_TOOL_NAMES = new Set([
  "escalate_to_human", "search_banking_knowledge", "vector_search",
  "web_search", "calculate", "calculator", "get_current_time",
  "get_datetime", "get_current_datetime",
]);

const BARE_TOOL_NAME_RE = /^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+$/;
const ROLE_LABEL_RE = /^(User|Assistant|Human|Bot)\s*:/i;
// Detect "Note:" / "Note :" lines so we can render a callout box
const NOTE_LINE_RE = /^(\*\*)?note:?(\*\*)?/i;

function normalizeMarkdown(text: string): string {
  return (
    text
      .replace(/([^\n])(\d+\.\s)/g, "$1\n$2")
      .replace(/([^\n])(- (?!-))/g, "$1\n$2")
      .replace(/([^\n])(\*\*[A-Z][^*]+\*\*:)/g, "$1\n$2")
      .replace(/\n{3,}/g, "\n\n")
  );
}

function sanitizeAgentText(text: string): string {
  const lines = text.split("\n");
  const cleaned: string[] = [];
  let skipRest = false;

  for (const line of lines) {
    const trimmed = line.trim();
    if (ROLE_LABEL_RE.test(trimmed)) { skipRest = true; }
    if (skipRest) continue;
    if (TOOL_JSON_RE.test(trimmed)) continue;
    if (BARE_TOOL_NAME_RE.test(trimmed) && KNOWN_TOOL_NAMES.has(trimmed.toLowerCase())) continue;
    cleaned.push(line);
  }

  return normalizeMarkdown(cleaned.join("\n").trim());
}

/** Paragraph component — detects "Note:" lines and renders a callout */
function MdParagraph({ children }: { children?: ReactNode }) {
  const text = typeof children === "string" ? children : "";
  const isNote = NOTE_LINE_RE.test(text);
  if (isNote) {
    return (
      <p className="my-1.5 px-3 py-2 bg-[#EEF2FF] border-l-[3px] border-[#1A56DB] rounded-r-md text-[0.83em] text-[#334155] leading-relaxed">
        {children}
      </p>
    );
  }
  return <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>;
}

export function AgentMessage({ message }: Props) {
  return (
    <div className="flex items-start gap-2.5 px-4 py-1.5">
      {/* Sparkle avatar */}
      <div className="w-8 h-8 rounded-full bg-[#1A56DB] flex items-center justify-center flex-shrink-0 mt-0.5 shadow-sm">
        <Sparkles size={14} className="text-white" strokeWidth={1.8} />
      </div>

      {/* Bubble + timestamp */}
      <div className="flex flex-col gap-1 max-w-[88%] md:max-w-[72%] xl:max-w-[680px]">
        <div className="bg-white border border-gray-100 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-gray-800 shadow-sm">
          <div className="agent-markdown">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                p: MdParagraph,
                img: ({ src, alt }) => (
                  <img
                    src={src}
                    alt={alt ?? ""}
                    loading="lazy"
                    className="rounded-xl my-3 max-w-full w-full object-contain border border-gray-100 shadow-sm"
                  />
                ),
                a: ({ href, children }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[#1A56DB] underline underline-offset-2"
                  >
                    {children}
                  </a>
                ),
              }}
            >
              {sanitizeAgentText(message.text)}
            </ReactMarkdown>

            {message.streaming && (
              <span
                aria-hidden="true"
                className="inline-block w-[2px] h-[1em] bg-[#1A56DB] ml-0.5 align-middle animate-pulse"
              />
            )}
          </div>
        </div>
        {!message.streaming && (
          <span className="text-[11px] text-gray-400 pl-0.5">
            {formatTime(message.timestamp)}
          </span>
        )}
      </div>
    </div>
  );
}

