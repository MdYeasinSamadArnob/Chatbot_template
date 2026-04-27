"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Shield } from "lucide-react";
import type { AgentTextMessage as AgentTextMessageType } from "@/store/types";

interface Props {
  message: AgentTextMessageType;
}

export function AgentMessage({ message }: Props) {
  return (
    <div className="flex items-start gap-2.5 px-4 py-1.5">
      {/* Bank avatar */}
      <div className="w-8 h-8 rounded-full bg-[#1A56DB] flex items-center justify-center flex-shrink-0 mt-0.5 shadow-sm">
        <Shield size={14} className="text-white" />
      </div>

      {/* Message bubble */}
      <div className="max-w-[85%] bg-white border border-gray-100 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-gray-800 shadow-sm">
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
            {message.text}
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

