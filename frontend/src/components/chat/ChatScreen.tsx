"use client";

import { useSearchParams } from "next/navigation";
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
  const urlConversationId = searchParams.get("conversation_id") ?? undefined;

  const { submitInput, cancelRequest, resetConversation, isProcessing, errorMessages, connectionStatus } =
    useChat(urlConversationId);

  return (
    <div className="h-screen w-full overflow-hidden bg-[radial-gradient(circle_at_top,#eaf1ff_0%,#f5f7ff_45%,#edf2ff_100%)] md:p-4">
      <div className="mx-auto flex h-full w-full max-w-[980px] flex-col overflow-hidden bg-[#F5F7FF] md:rounded-3xl md:border md:border-slate-200/70 md:bg-white/75 md:backdrop-blur md:shadow-[0_18px_60px_rgba(15,23,42,0.16)]">
        <ChatHeader
          onReset={resetConversation}
          connectionStatus={connectionStatus}
        />

        {/* Error banner */}
        {errorMessages.length > 0 && (
          <div className="bg-red-50 border-b border-red-200 px-4 py-2 flex-shrink-0">
            {errorMessages.map((msg, i) => (
              <p key={i} className="text-xs text-red-600">
                {msg}
              </p>
            ))}
          </div>
        )}

        <ChatContainer onSuggestion={submitInput} />

        <ChatEditor
          onSubmit={submitInput}
          onCancel={cancelRequest}
          isProcessing={isProcessing}
        />
      </div>
    </div>
  );
}
