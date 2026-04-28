/**
 * useChat — Socket.IO driven chat hook for Bank Help Bot.
 *
 * Connects to the backend Socket.IO server on mount, registers
 * all event handlers, and exposes submitInput / cancelRequest /
 * resetConversation to the UI layer.
 */

"use client";

import { useEffect, useRef, useCallback } from "react";
import { socketClient } from "@/lib/socketClient";
import { useChatStore } from "@/store/chatStore";

export function useChat(conversationId?: string) {
  const store = useChatStore();
  const isProcessingRef = useRef(false);

  // Use provided conversationId or the one from the store
  const effectiveConversationId = conversationId ?? store.conversationId;

  useEffect(() => {
    // ── Register Socket.IO event handlers ─────────────────────────────

    const onConnect = () => {
      store.setConnectionStatus("connected");
    };

    const onDisconnect = (reason: string) => {
      store.setConnectionStatus(
        reason === "io client disconnect" ? "disconnected" : "reconnecting"
      );
      store.removeThinking();
      store.setProcessing(false);
      isProcessingRef.current = false;
    };

    const onConnectError = (_err: Error) => {
      store.setConnectionStatus("reconnecting");
    };

    socketClient.onConnect(onConnect);
    socketClient.onDisconnect(onDisconnect);
    socketClient.onConnectError(onConnectError);

    socketClient.on("connected", ({ conversation_id }) => {
      // Backend confirmed connection, conversation_id may be server-assigned
      // We already know it from our query param
    });

    socketClient.on("history", ({ messages }) => {
      store.loadHistory(messages);
    });

    socketClient.on("thinking_start", () => {
      store.addThinking();
    });

    socketClient.on("thinking_end", () => {
      store.removeThinking();
    });

    socketClient.on("text_delta", ({ delta }) => {
      store.removeThinking();
      store.addAgentTextDelta(delta);
    });

    socketClient.on("tool_call", ({ toolCallId, toolName, args, announcement }) => {
      store.toolCallStart(toolCallId, toolName, args, announcement);
    });

    socketClient.on("tool_result", ({ toolCallId, result }) => {
      store.toolCallEnd(toolCallId, result);
    });

    socketClient.on("state", (data) => {
      // Extract suggested_actions before passing the rest to session state
      const { suggested_actions, ...sessionData } = data as any;
      store.updateSessionState(sessionData as any);
      if (Array.isArray(suggested_actions)) {
        store.setSuggestedActions(suggested_actions);
      }
    });

    socketClient.on("error", ({ message }) => {
      store.removeThinking();
      store.addErrorMessage(message);
      store.setProcessing(false);
      isProcessingRef.current = false;
    });

    socketClient.on("finish", (data?: { suggestedActions?: unknown }) => {
      store.removeThinking();
      store.finishStreaming();
      store.setProcessing(false);
      isProcessingRef.current = false;
      // Update quick-reply chips — delivered here to guarantee they reflect
      // the current intent and are never overwritten by stale mid-loop state.
      const chips = (data as any)?.suggestedActions;
      if (Array.isArray(chips)) {
        store.setSuggestedActions(chips);
      }
    });

    socketClient.on("conversation_reset", () => {
      store.resetConversation();
    });

    // chips_update: mid-stream chip push from background classify task
    socketClient.on("chips_update", (data) => {
      if (Array.isArray(data?.suggestedActions)) {
        store.setSuggestedActions(data.suggestedActions);
      }
    });

    // ── Connect ──────────────────────────────────────────────────────
    socketClient.connect(effectiveConversationId);

    return () => {
      // Clean up listeners on unmount
      socketClient.offConnect(onConnect);
      socketClient.offDisconnect(onDisconnect);
      socketClient.offConnectError(onConnectError);
      socketClient.off("connected");
      socketClient.off("history");
      socketClient.off("thinking_start");
      socketClient.off("thinking_end");
      socketClient.off("text_delta");
      socketClient.off("tool_call");
      socketClient.off("tool_result");
      socketClient.off("state");
      socketClient.off("error");
      socketClient.off("finish");
      socketClient.off("chips_update");
      socketClient.off("conversation_reset");
      socketClient.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveConversationId]);

  const submitInput = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isProcessingRef.current) return;

      isProcessingRef.current = true;
      store.addUserMessage(trimmed);
      store.setProcessing(true);

      socketClient.emit("chat_message", {
        message: trimmed,
        conversation_id: effectiveConversationId,
        profile: "banking",
      });
    },
    [effectiveConversationId, store]
  );

  const cancelRequest = useCallback(() => {
    // Socket.IO doesn't have mid-stream cancellation like fetch AbortController.
    // We stop processing on the client side; the server will complete but
    // the UI ignores remaining events.
    store.removeThinking();
    store.setProcessing(false);
    isProcessingRef.current = false;
  }, [store]);

  const resetConversation = useCallback(() => {
    socketClient.emit("reset_conversation", {
      conversation_id: effectiveConversationId,
    });
    store.resetConversation();
  }, [effectiveConversationId, store]);

  return {
    messages: store.messages,
    errorMessages: store.errorMessages,
    isProcessing: store.isProcessing,
    connectionStatus: store.connectionStatus,
    conversationId: effectiveConversationId,
    submitInput,
    cancelRequest,
    resetConversation,
  };
}

