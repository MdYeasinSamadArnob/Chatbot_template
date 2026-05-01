"use client";

import { ArrowLeft, Trash2 } from "lucide-react";

interface Props {
  onReset: () => void;
  hasMessages: boolean;
}

export function ChatHeader({ onReset, hasMessages }: Props) {
  return (
    <div className="flex items-center h-14 px-2 bg-white border-b border-gray-200 flex-shrink-0">
      {/* Back arrow */}
      <button
        onClick={() => window.history.back()}
        className="w-10 h-10 flex items-center justify-center rounded-full text-gray-700 hover:bg-gray-100 active:bg-gray-200 transition-colors active:scale-95"
        aria-label="Go back"
      >
        <ArrowLeft size={22} strokeWidth={2} />
      </button>

      {/* Centered title */}
      <h1 className="flex-1 text-center text-base font-bold text-gray-900 tracking-tight">
        BA Smart Assistant
      </h1>

      {/* Trash — only visible when there are messages */}
      {hasMessages ? (
        <button
          onClick={onReset}
          className="w-10 h-10 flex items-center justify-center rounded-full text-gray-500 hover:bg-gray-100 active:bg-gray-200 transition-colors active:scale-95"
          aria-label="Clear chat"
        >
          <Trash2 size={20} strokeWidth={1.8} />
        </button>
      ) : (
        <div className="w-10" />
      )}
    </div>
  );
}
