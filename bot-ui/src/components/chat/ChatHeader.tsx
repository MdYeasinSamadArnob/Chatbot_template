"use client";

import { ArrowLeft, Trash2 } from "lucide-react";

interface Props {
  onReset: () => void;
  hasMessages: boolean;
  username?: string;
}

export function ChatHeader({ onReset, hasMessages, username }: Props) {
  const firstName = username ? username.trim().split(" ")[0] : null;

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

      {/* Centered title + optional greeting subtitle */}
      <div className="flex-1 flex flex-col items-center">
        <h1 className="text-base font-bold text-gray-900 tracking-tight leading-tight">
          BA Smart Assistant
        </h1>
        {firstName && (
          <p className="text-xs text-[#1A56DB] font-medium leading-tight">
            Hi, {firstName}!
          </p>
        )}
      </div>

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
