"use client";

import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { TriangleAlert } from "lucide-react";
import { useChat } from "@/hooks/useChat";
import { ChatHeader } from "./ChatHeader";
import { ChatContainer } from "./ChatContainer";
import { ChatEditor } from "./ChatEditor";
import { useChatStore } from "@/store/chatStore";

/**
 * Full-screen chat layout for the banking help bot webview.
 * Takes up 100% of the viewport — designed for Android WebView.
 */
export function ChatScreen() {
  const searchParams = useSearchParams();

  // Identity params from WebView URL
  const userId        = searchParams.get("user_id") ?? undefined;
  const username      = searchParams.get("username") ?? undefined;
  const screenContext = searchParams.get("screen_context") ?? undefined;
  const timestamp     = searchParams.get("timestamp") ?? undefined;
  const signature     = searchParams.get("signature") ?? undefined;
  const urlConvId     = searchParams.get("conversation_id") ?? undefined;

  // Per-user localStorage key — read on client only (SSR safe)
  const [storedConvId, setStoredConvId] = useState<string | undefined>(undefined);
  useEffect(() => {
    if (userId && typeof window !== "undefined") {
      const stored = localStorage.getItem(`ba_conv_id:${userId}`) ?? undefined;
      setStoredConvId(stored);
    }
  }, [userId]);

  // Prefer URL conv_id (reload), then localStorage (soft-nav resume)
  const conversationId = urlConvId ?? storedConvId;

  const {
    submitInput,
    cancelRequest,
    resetConversation,
    isProcessing,
    errorMessages,
    userContext,
    hasPreviousSession,
    loadPreviousSession,
  } = useChat(conversationId, { userId, username, screenContext, timestamp, signature });

  const messages = useChatStore((s) => s.messages);
  const [showClearDialog, setShowClearDialog] = useState(false);

  function handleClearConfirm() {
    setShowClearDialog(false);
    resetConversation();
  }

  return (
    <div className="h-screen w-full flex flex-col overflow-hidden bg-[#EAECF0]">
      <ChatHeader
        onReset={() => setShowClearDialog(true)}
        hasMessages={messages.length > 0}
        username={userContext.username}
      />

      {/* Error banner */}
      {errorMessages.length > 0 && (
        <div className="bg-red-50 border-b border-red-200 px-4 py-2 flex-shrink-0">
          {errorMessages.map((msg, i) => (
            <p key={i} className="text-xs text-red-600">{msg}</p>
          ))}
        </div>
      )}

      <ChatContainer
        onSuggestion={submitInput}
        screenContext={userContext.screenContext}
        hasPreviousSession={hasPreviousSession}
        onLoadPrevious={loadPreviousSession}
        username={userContext.username}
      />

      <ChatEditor
        onSubmit={submitInput}
        onCancel={cancelRequest}
        isProcessing={isProcessing}
      />

      {/* Clear Chat Confirmation Dialog */}
      {showClearDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-6">
          <div className="bg-white rounded-2xl w-full max-w-xs shadow-2xl overflow-hidden">
            <div className="flex flex-col items-center px-6 pt-8 pb-6 gap-3">
              <div className="w-14 h-14 flex items-center justify-center">
                <TriangleAlert size={48} strokeWidth={1.5} className="text-[#1A56DB]" />
              </div>
              <h2 className="text-xl font-bold text-gray-900 text-center">Clear Chat</h2>
              <p className="text-sm text-gray-500 text-center leading-relaxed">
                Are you sure you want to clear the entire conversation?
              </p>
            </div>
            <div className="flex border-t border-gray-100">
              <button
                onClick={() => setShowClearDialog(false)}
                className="flex-1 py-4 text-sm font-bold text-gray-700 tracking-wide border-r border-gray-100 hover:bg-gray-50 active:bg-gray-100 transition-colors"
              >
                CANCEL
              </button>
              <button
                onClick={handleClearConfirm}
                className="flex-1 py-4 text-sm font-bold text-white bg-[#1A56DB] hover:bg-[#1648c0] active:bg-[#1340a8] transition-colors"
              >
                CLEAR
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
