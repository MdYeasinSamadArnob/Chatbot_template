"use client";

import { Search, FileText, Clock } from "lucide-react";
import type { ToolCallMessage as ToolCallMessageType } from "@/store/types";

interface Props {
  message: ToolCallMessageType;
}

/** Friendly label shown to bank customers while a tool is running. */
const TOOL_LABELS: Record<string, { icon: React.ReactNode; text: string }> = {
  search_banking_knowledge: {
    icon: <Search size={13} className="text-[#1A56DB]" />,
    text: "Searching our knowledge base…",
  },
  calculate: {
    icon: <FileText size={13} className="text-[#1A56DB]" />,
    text: "Calculating…",
  },
  get_current_time: {
    icon: <Clock size={13} className="text-[#1A56DB]" />,
    text: "Checking the time…",
  },
};

const DEFAULT_LABEL = {
  icon: <Search size={13} className="text-[#1A56DB]" />,
  text: "Looking that up for you…",
};

/**
 * Shown while a backend tool is running.
 * Disappears completely once the tool finishes (store removes the message).
 * Regular bank customers never see raw tool names, JSON args, or results.
 */
export function ToolCallMessage({ message }: Props) {
  // Only render while running — done/error messages are removed by the store
  if (message.status !== "running") return null;

  const label = TOOL_LABELS[message.toolName] ?? DEFAULT_LABEL;

  return (
    <div className="flex items-start gap-2.5 px-4 py-1">
      {/* Matches the agent avatar size/position */}
      <div className="w-8 h-8 rounded-full bg-[#1A56DB]/10 flex items-center justify-center flex-shrink-0 mt-0.5">
        {label.icon}
      </div>

      <div className="flex items-center gap-2 bg-white border border-blue-100 rounded-2xl rounded-tl-sm px-4 py-2.5 shadow-sm">
        {/* Animated dots */}
        <span className="thinking-dot w-1.5 h-1.5 rounded-full bg-[#1A56DB] inline-block opacity-40" />
        <span className="thinking-dot w-1.5 h-1.5 rounded-full bg-[#1A56DB] inline-block opacity-40" />
        <span className="thinking-dot w-1.5 h-1.5 rounded-full bg-[#1A56DB] inline-block opacity-40" />
        <span className="text-sm text-gray-500 ml-1">{label.text}</span>
      </div>
    </div>
  );
}
