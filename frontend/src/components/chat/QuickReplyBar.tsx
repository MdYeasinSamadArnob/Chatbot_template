"use client";

import { useEffect, useRef } from "react";

export interface SuggestedAction {
  label: string;
  value: string;
}

interface Props {
  actions: SuggestedAction[];
  onSelect: (value: string) => void;
  disabled?: boolean;
}

/**
 * QuickReplyBar — horizontal scrollable chip row rendered below the last
 * agent message. Disappears as soon as the user sends any message (the
 * store clears suggestedActions on addUserMessage).
 */
export function QuickReplyBar({ actions, onSelect, disabled = false }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Scroll to the first chip on mount / when actions change
  useEffect(() => {
    scrollRef.current?.scrollTo({ left: 0, behavior: "smooth" });
  }, [actions]);

  if (!actions.length) return null;

  return (
    <div
      ref={scrollRef}
      className="flex gap-2 overflow-x-auto py-2 px-4 pb-3 no-scrollbar"
      style={{ WebkitOverflowScrolling: "touch" }}
      role="group"
      aria-label="Quick reply options"
    >
      {actions.map((action) => (
        <button
          key={action.value}
          onClick={() => !disabled && onSelect(action.value)}
          disabled={disabled}
          className={[
            "flex-shrink-0 text-sm font-medium rounded-full px-4 py-2 border transition-colors",
            "whitespace-nowrap min-h-[36px] active:scale-[0.97]",
            disabled
              ? "opacity-50 cursor-not-allowed bg-white border-gray-200 text-gray-400"
              : "bg-white border-[#1A56DB] text-[#1A56DB] hover:bg-blue-50 cursor-pointer shadow-sm",
          ].join(" ")}
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}
