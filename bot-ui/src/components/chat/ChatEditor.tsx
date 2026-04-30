"use client";

import { useState, useRef, useCallback } from "react";
import { Send, StopCircle } from "lucide-react";
import clsx from "clsx";

interface Props {
  onSubmit: (text: string) => void;
  onCancel: () => void;
  isProcessing: boolean;
}

/**
 * Mobile-first chat input.
 * - Auto-resizing textarea
 * - safe-area-inset-bottom aware for Android/iOS notch
 * - 44px min touch target on send button (WCAG 2.5.5)
 */
export function ChatEditor({ onSubmit, onCancel, isProcessing }: Props) {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = useCallback(() => {
    const text = input.trim();
    if (!text || isProcessing) return;
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
    onSubmit(text);
  }, [input, isProcessing, onSubmit]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setInput(e.target.value);
      const ta = e.target;
      ta.style.height = "auto";
      ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
    },
    []
  );

  const canSend = input.trim().length > 0 && !isProcessing;

  return (
    <div
      className="flex-shrink-0 px-3 pt-2 pb-3 bg-white border-t border-gray-200"
      style={{ paddingBottom: "calc(0.75rem + env(safe-area-inset-bottom))" }}
    >
      <div className="mx-auto w-full max-w-[920px] flex items-end gap-2 bg-[#F5F7FF] rounded-2xl border border-gray-200 focus-within:border-[#1A56DB] focus-within:ring-2 focus-within:ring-blue-100 transition-all px-4 py-2.5 shadow-sm">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder="Ask about banking services…"
          rows={1}
          className="flex-1 bg-transparent resize-none outline-none text-sm text-gray-800 placeholder-gray-400 leading-relaxed"
          style={{ maxHeight: "10rem" }}
        />

        <button
          onClick={isProcessing ? onCancel : handleSubmit}
          disabled={!isProcessing && !canSend}
          title={isProcessing ? "Stop" : "Send"}
          className={clsx(
            "min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full transition-all flex-shrink-0 active:scale-95",
            isProcessing
              ? "bg-red-100 text-red-600 hover:bg-red-200"
              : canSend
              ? "bg-[#1A56DB] text-white hover:bg-[#1648c0] shadow-sm"
              : "text-gray-300 cursor-not-allowed"
          )}
        >
          {isProcessing ? <StopCircle size={18} /> : <Send size={17} />}
        </button>
      </div>
    </div>
  );
}

