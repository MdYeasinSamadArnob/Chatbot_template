"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Shield } from "lucide-react";
import type { AgentTextMessage as AgentTextMessageType } from "@/store/types";

interface Props {
  message: AgentTextMessageType;
}

/**
 * Safety filter: strip leaked tool/role content before rendering.
 * Catches:
 *   - Tool-call JSON blobs: {"type": "function", ...} / {"name": ..., "arguments": ...}
 *   - Bare tool names on their own line: Escalate_to_human
 *   - Role labels that start fake dialogue: "User:" / "Assistant:"
 */
const TOOL_JSON_RE =
  /^\s*\{\s*"(?:type"\s*:\s*"function"|name"\s*:\s*"[a-zA-Z_][a-zA-Z0-9_]*")/;

const KNOWN_TOOL_NAMES = new Set([
  "escalate_to_human", "search_banking_knowledge", "vector_search",
  "web_search", "calculate", "calculator", "get_current_time",
  "get_datetime", "get_current_datetime",
]);

// snake_case identifier alone on a line
const BARE_TOOL_NAME_RE = /^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+$/;

// "User:", "Assistant:", "Human:", "Bot:" — signals a fake transcript
const ROLE_LABEL_RE = /^(User|Assistant|Human|Bot)\s*:/i;

/**
 * Fix inline numbered lists the model emits without newlines.
 * e.g. "follow these steps:1. Log in...2. Navigate..." →
 *      "follow these steps:\n1. Log in...\n2. Navigate..."
 */
function normalizeMarkdown(text: string): string {
  return (
    text
      // Insert \n before numbered list items not already on their own line
      .replace(/([^\n])(\d+\.\s)/g, "$1\n$2")
      // Insert \n before bullet items not on their own line
      .replace(/([^\n])(- (?!-))/g, "$1\n$2")
      // Insert \n before bold headings mid-line (e.g. "text**Heading**")
      .replace(/([^\n])(\*\*[A-Z][^*]+\*\*:)/g, "$1\n$2")
      // Collapse 3+ consecutive newlines to 2
      .replace(/\n{3,}/g, "\n\n")
  );
}

function sanitizeAgentText(text: string): string {
  const lines = text.split("\n");
  const cleaned: string[] = [];
  let skipRest = false; // once a role label is detected, drop everything after

  for (const line of lines) {
    const trimmed = line.trim();

    if (ROLE_LABEL_RE.test(trimmed)) {
      skipRest = true;
    }
    if (skipRest) continue;

    if (TOOL_JSON_RE.test(trimmed)) continue;
    if (
      BARE_TOOL_NAME_RE.test(trimmed) &&
      KNOWN_TOOL_NAMES.has(trimmed.toLowerCase())
    ) continue;

    cleaned.push(line);
  }

  return normalizeMarkdown(cleaned.join("\n").trim());
}

export function AgentMessage({ message }: Props) {
  return (
    <div className="flex items-start gap-2.5 px-4 py-1.5">
      {/* Bank avatar */}
      <div className="w-8 h-8 rounded-full bg-[#1A56DB] flex items-center justify-center flex-shrink-0 mt-0.5 shadow-sm">
        <Shield size={14} className="text-white" />
      </div>

      {/* Message bubble */}
      <div className="max-w-[88%] md:max-w-[72%] xl:max-w-[680px] bg-white border border-gray-100 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-gray-800 shadow-sm">
        <div className="agent-markdown">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              // Inline images render between text — rounded, lazy loaded
              img: ({ src, alt }) => (
                <img
                  src={src}
                  alt={alt ?? ""}
                  loading="lazy"
                  className="rounded-xl my-3 max-w-full w-full object-contain border border-gray-100 shadow-sm"
                />
              ),
              // Open all links safely in a new tab
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

          {/* Blinking cursor while streaming */}
          {message.streaming && (
            <span
              aria-hidden="true"
              className="inline-block w-[2px] h-[1em] bg-[#1A56DB] ml-0.5 align-middle animate-pulse"
            />
          )}
        </div>
      </div>
    </div>
  );
}

