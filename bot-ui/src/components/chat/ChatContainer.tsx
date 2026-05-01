"use client";

import { useEffect, useRef } from "react";
import { Sparkles, CreditCard, ArrowLeftRight, Lock, FileText } from "lucide-react";
import { useChatStore } from "@/store/chatStore";
import { MessageDispatcher } from "./messages/MessageDispatcher";
import { QuickReplyBar } from "./QuickReplyBar";

const QUICK_ACTIONS = [
  { label: "Check my balance", value: "How do I check my balance?", icon: CreditCard },
  { label: "How to transfer", value: "How do I transfer money?", icon: ArrowLeftRight },
  { label: "Change my PIN", value: "How do I change my PIN?", icon: Lock },
  { label: "View transactions", value: "How do I view my transactions?", icon: FileText },
];

interface Props {
  onSuggestion?: (text: string) => void;
}

export function ChatContainer({ onSuggestion }: Props) {
  const messages = useChatStore((s) => s.messages);
  const suggestedActions = useChatStore((s) => s.suggestedActions);
  const isProcessing = useChatStore((s) => s.isProcessing);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, suggestedActions]);

  return (
    <div className="flex-1 overflow-y-auto overscroll-none flex flex-col bg-[#EAECF0]">
      {messages.length === 0 ? (
        <EmptyState onSuggestion={onSuggestion} />
      ) : (
        <div className="py-3 space-y-1 pb-2 flex-1 w-full max-w-[920px] mx-auto">
          {messages.map((msg) => (
            <MessageDispatcher key={msg.id} message={msg} />
          ))}
        </div>
      )}

      {/* Quick-reply chips — shown below last message */}
      {suggestedActions.length > 0 && onSuggestion && (
        <div className="w-full max-w-[920px] mx-auto">
          <QuickReplyBar
            actions={suggestedActions}
            onSelect={onSuggestion}
            disabled={isProcessing}
          />
        </div>
      )}

      <div ref={bottomRef} className="h-2" />
    </div>
  );
}

function EmptyState({ onSuggestion }: { onSuggestion?: (t: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 flex-1 gap-0">
      {/* Sparkle icon */}
      <div className="w-24 h-24 rounded-full bg-[#1A56DB] flex items-center justify-center mb-6 shadow-md">
        <Sparkles size={42} className="text-white" strokeWidth={1.8} />
      </div>

      <h2 className="text-2xl font-bold text-[#1A56DB] mb-2 text-center">
        BA Smart Assistant
      </h2>
      <p className="text-sm text-gray-500 text-center mb-10 leading-relaxed">
        Ask me anything about<br />your banking needs
      </p>

      {/* 2×2 quick action grid */}
      {onSuggestion && (
        <div className="grid grid-cols-2 gap-3 w-full max-w-xs">
          {QUICK_ACTIONS.map(({ label, value, icon: Icon }) => (
            <button
              key={value}
              onClick={() => onSuggestion(value)}
              className="flex items-center gap-2.5 bg-white rounded-2xl px-4 py-3.5 text-left text-sm text-gray-700 font-medium shadow-sm border border-gray-100 hover:border-[#1A56DB] hover:bg-blue-50 active:scale-[0.97] transition-all"
            >
              <Icon size={18} className="text-[#1A56DB] flex-shrink-0" strokeWidth={1.8} />
              <span className="leading-tight line-clamp-2">{label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

