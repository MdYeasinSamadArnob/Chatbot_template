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
    <div className="px-3 pb-2 pt-1 md:px-4 md:pb-3">
      <div
        ref={scrollRef}
        className="no-scrollbar flex gap-2 overflow-x-auto md:flex-wrap md:overflow-visible"
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
              "inline-flex items-center justify-center rounded-full border px-3.5 py-2 text-xs md:text-sm font-medium",
              "min-h-[36px] whitespace-nowrap transition-all duration-150 active:scale-[0.97]",
              "shadow-[0_2px_10px_rgba(15,23,42,0.07)]",
              disabled
                ? "cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400"
                : "cursor-pointer border-blue-200 bg-white text-[#1A56DB] hover:border-[#1A56DB] hover:bg-blue-50",
            ].join(" ")}
          >
            {action.label}
          </button>
        ))}
      </div>
    </div>
  );
}
