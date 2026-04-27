"use client";

import { useEffect, useRef } from "react";
import { Shield } from "lucide-react";
import { useChatStore } from "@/store/chatStore";
import { MessageDispatcher } from "./messages/MessageDispatcher";

const BANKING_SUGGESTIONS = [
  "How do I transfer money to another account?",
  "How do I block or replace my card?",
  "How do I set up mobile banking?",
  "How do I update my personal details?",
  "What are the loan and credit requirements?",
];

interface Props {
  onSuggestion?: (text: string) => void;
}

export function ChatContainer({ onSuggestion }: Props) {
  const messages = useChatStore((s) => s.messages);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex-1 overflow-y-auto overscroll-none">
      {messages.length === 0 ? (
        <EmptyState onSuggestion={onSuggestion} />
      ) : (
        <div className="py-3 space-y-1 pb-2">
          {messages.map((msg) => (
            <MessageDispatcher key={msg.id} message={msg} />
          ))}
        </div>
      )}
      <div ref={bottomRef} className="h-2" />
    </div>
  );
}

function EmptyState({ onSuggestion }: { onSuggestion?: (t: string) => void }) {
  return (
    <div className="flex flex-col items-center px-4 pt-10 pb-6">
      {/* Icon */}
      <div className="w-14 h-14 rounded-2xl bg-[#1A56DB] flex items-center justify-center mb-4 shadow-lg">
        <Shield size={26} className="text-white" />
      </div>
      <h3 className="text-base font-semibold text-gray-900 mb-1 text-center">
        How can we help you?
      </h3>
      <p className="text-sm text-gray-500 leading-relaxed text-center max-w-[260px] mb-6">
        Ask anything about your bank account, cards, transfers, loans, or services.
      </p>

      {/* Suggestion chips */}
      {onSuggestion && (
        <div className="w-full space-y-2">
          {BANKING_SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => onSuggestion(s)}
              className="w-full text-left text-sm text-gray-700 bg-white border border-gray-200 hover:border-[#1A56DB] hover:bg-blue-50 rounded-2xl px-4 py-3 transition-colors shadow-sm active:scale-[0.98]"
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

