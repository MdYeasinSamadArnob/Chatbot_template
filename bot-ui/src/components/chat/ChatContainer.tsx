"use client";

import { useEffect, useRef } from "react";
import { Sparkles, CreditCard, ArrowLeftRight, Lock, FileText, Send, Banknote, Globe, Users, BarChart2, ClipboardList, ShieldOff, Zap, DollarSign, TrendingUp } from "lucide-react";
import { useChatStore } from "@/store/chatStore";
import { MessageDispatcher } from "./messages/MessageDispatcher";
import { QuickReplyBar } from "./QuickReplyBar";

type QuickAction = { label: string; value: string; icon: React.ElementType };

const QUICK_ACTIONS_DEFAULT: QuickAction[] = [
  { label: "Check my balance", value: "How do I check my balance?", icon: CreditCard },
  { label: "How to transfer", value: "How do I transfer money?", icon: ArrowLeftRight },
  { label: "Change my PIN", value: "How do I change my PIN?", icon: Lock },
  { label: "View transactions", value: "How do I view my transactions?", icon: FileText },
];

const QUICK_ACTIONS_MAP: Record<string, QuickAction[]> = {
  transfer: [
    { label: "Transfer money", value: "How do I transfer money?", icon: Send },
    { label: "Transfer limits", value: "What are my transfer limits?", icon: BarChart2 },
    { label: "International transfer", value: "How do I send money internationally?", icon: Globe },
    { label: "Add beneficiary", value: "How do I add a beneficiary?", icon: Users },
  ],
  balance_check: [
    { label: "Check balance", value: "What is my current balance?", icon: CreditCard },
    { label: "Mini statement", value: "Show my mini statement", icon: ClipboardList },
    { label: "View transactions", value: "Show my recent transactions", icon: FileText },
    { label: "Account details", value: "Show my account details", icon: Banknote },
  ],
  card_services: [
    { label: "Block card", value: "How do I block my card?", icon: ShieldOff },
    { label: "Card activation", value: "How do I activate my card?", icon: Zap },
    { label: "Card limit", value: "How do I change my card limit?", icon: BarChart2 },
    { label: "Replace card", value: "How do I get a replacement card?", icon: CreditCard },
  ],
  loans: [
    { label: "Loan eligibility", value: "Am I eligible for a loan?", icon: TrendingUp },
    { label: "Apply for loan", value: "How do I apply for a loan?", icon: DollarSign },
    { label: "EMI calculator", value: "Can you calculate my loan EMI?", icon: BarChart2 },
    { label: "Loan status", value: "What is my loan application status?", icon: ClipboardList },
  ],
};

function getQuickActions(screenContext?: string): QuickAction[] {
  if (screenContext && QUICK_ACTIONS_MAP[screenContext]) {
    return QUICK_ACTIONS_MAP[screenContext];
  }
  return QUICK_ACTIONS_DEFAULT;
}

interface Props {
  onSuggestion?: (text: string) => void;
  screenContext?: string;
  hasPreviousSession?: boolean;
  onLoadPrevious?: () => void;
  username?: string;
}

export function ChatContainer({ onSuggestion, screenContext, hasPreviousSession, onLoadPrevious, username }: Props) {
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
        <EmptyState
          onSuggestion={onSuggestion}
          screenContext={screenContext}
          hasPreviousSession={hasPreviousSession}
          onLoadPrevious={onLoadPrevious}
          username={username}
        />
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

interface EmptyStateProps {
  onSuggestion?: (t: string) => void;
  screenContext?: string;
  hasPreviousSession?: boolean;
  onLoadPrevious?: () => void;
  username?: string;
}

function EmptyState({ onSuggestion, screenContext, hasPreviousSession, onLoadPrevious, username }: EmptyStateProps) {
  const firstName = username ? username.trim().split(" ")[0] : null;
  const quickActions = getQuickActions(screenContext);

  return (
    <div className="flex flex-col items-center justify-center px-6 flex-1 gap-0">
      {/* Sparkle icon */}
      <div className="w-24 h-24 rounded-full bg-[#1A56DB] flex items-center justify-center mb-6 shadow-md">
        <Sparkles size={42} className="text-white" strokeWidth={1.8} />
      </div>

      <h2 className="text-2xl font-bold text-[#1A56DB] mb-2 text-center">
        {firstName ? `Hello, ${firstName}!` : "BA Smart Assistant"}
      </h2>
      <p className="text-sm text-gray-500 text-center mb-6 leading-relaxed">
        Ask me anything about<br />your banking needs
      </p>

      {/* Continue from last chat */}
      {hasPreviousSession && onLoadPrevious && (
        <button
          onClick={onLoadPrevious}
          className="mb-6 px-5 py-2.5 rounded-full border border-[#1A56DB] text-[#1A56DB] text-sm font-semibold hover:bg-blue-50 active:scale-[0.97] transition-all"
        >
          Continue from last chat
        </button>
      )}

      {/* 2×2 quick action grid */}
      {onSuggestion && (
        <div className="grid grid-cols-2 gap-3 w-full max-w-xs">
          {quickActions.map(({ label, value, icon: Icon }) => (
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

