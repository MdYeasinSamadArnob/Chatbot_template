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
import type { RetrievedSource } from "@/store/types";

function normalizeSources(input: unknown): RetrievedSource[] {
  if (!Array.isArray(input)) return [];

  return input
    .filter(
      (item): item is RetrievedSource =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as { id?: unknown }).id === "string" &&
        typeof (item as { document_title?: unknown }).document_title === "string"
    )
    .map((item) => ({
      ...item,
      content_text: typeof item.content_text === "string" ? item.content_text : "",
      image_urls: Array.isArray(item.image_urls) ? item.image_urls : [],
      render_blocks: Array.isArray(item.render_blocks) ? item.render_blocks : [],
    }));
}

export function useChat(conversationId?: string, userParams?: {
  userId?: string;
  username?: string;
  screenContext?: string;
  timestamp?: string;
  signature?: string;
}) {
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

    socketClient.on("user_context", (data) => {
      store.setUserContext({
        userId: data.user_id ?? undefined,
        username: data.username ?? undefined,
        screenContext: data.screen_context ?? undefined,
        isGuest: data.is_guest,
        convId: data.conv_id,
        hasPreviousSession: data.has_previous_session,
        prevConvId: data.prev_conv_id ?? undefined,
      });
    });

    socketClient.on("history_payload", ({ messages }) => {
      store.loadHistoryPayload(messages);
    });

    socketClient.on("thinking_start", () => {
      store.addThinking();
    });

    socketClient.on("thinking_end", () => {
      store.removeThinking();
    });

    socketClient.on("thinking_status", (payload: { label?: string }) => {
      const label = payload?.label ?? "";
      if (label) store.updateThinkingLabel(label);
    });

    socketClient.on("text_delta", (payload) => {
      const delta = payload?.delta ?? payload?.text ?? "";
      if (!delta) return;
      store.removeThinking();
      store.addAgentTextDelta(delta);
    });

    socketClient.on("tool_call", ({ toolCallId, toolName, args, announcement }) => {
      store.toolCallStart(toolCallId, toolName, args, announcement);
    });

    socketClient.on("tool_result", ({ toolCallId, result }) => {
      store.toolCallEnd(toolCallId, result);
    });

    socketClient.on("sources", (data) => {
      const sources = normalizeSources(data?.sources);
      if (sources.length) {
        store.setPendingSources(sources);
      }
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

    socketClient.on("finish", (data) => {
      store.removeThinking();
      store.finishStreaming();
      store.commitPendingSources();
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
    socketClient.connect(effectiveConversationId, userParams);

    return () => {
      // Clean up listeners on unmount
      socketClient.offConnect(onConnect);
      socketClient.offDisconnect(onDisconnect);
      socketClient.offConnectError(onConnectError);
      socketClient.off("connected");
      socketClient.off("history");
      socketClient.off("user_context");
      socketClient.off("history_payload");
      socketClient.off("thinking_start");
      socketClient.off("thinking_end");
      socketClient.off("thinking_status");
      socketClient.off("text_delta");
      socketClient.off("tool_call");
      socketClient.off("tool_result");
      socketClient.off("sources");
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

  const loadPreviousSession = useCallback(() => {
    const prevConvId = store.userContext.prevConvId;
    if (!prevConvId) return;
    socketClient.emit("load_previous_session", { prev_conv_id: prevConvId });
  }, [store.userContext.prevConvId]);

  return {
    messages: store.messages,
    errorMessages: store.errorMessages,
    isProcessing: store.isProcessing,
    connectionStatus: store.connectionStatus,
    conversationId: effectiveConversationId,
    userContext: store.userContext,
    hasPreviousSession: store.userContext.hasPreviousSession ?? false,
    prevConvId: store.userContext.prevConvId,
    submitInput,
    cancelRequest,
    resetConversation,
    loadPreviousSession,
  };
}

