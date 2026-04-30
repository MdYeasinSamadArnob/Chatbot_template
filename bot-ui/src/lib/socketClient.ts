/**
 * Singleton Socket.IO client for the Bank Help Bot.
 *
 * Usage:
 *   import { socketClient } from "@/lib/socketClient";
 *   socketClient.connect(conversationId);
 *   socketClient.onTextDelta((delta) => …);
 *   socketClient.emit("chat_message", { message, conversation_id });
 */

import { io, Socket } from "socket.io-client";

function resolveBotSocketUrl(): string {
  const configured = process.env.NEXT_PUBLIC_BOT_SOCKET_URL;

  if (typeof window === "undefined") {
    return configured ?? "http://localhost:9001";
  }

  const fallback = `${window.location.protocol}//${window.location.hostname}:9001`;
  if (!configured) return fallback;

  // If configured as localhost but UI is opened from another machine,
  // keep the configured port/path but swap host to the current browser host.
  try {
    const url = new URL(configured, window.location.origin);
    const host = url.hostname.toLowerCase();
    const isLocalhost = host === "localhost" || host === "127.0.0.1";
    const browserHost = window.location.hostname;
    const browserIsRemote = browserHost !== "localhost" && browserHost !== "127.0.0.1";

    if (isLocalhost && browserIsRemote) {
      url.hostname = browserHost;
      if (!url.port) {
        url.port = "9001";
      }
      return url.toString();
    }

    return url.toString();
  } catch {
    return fallback;
  }
}

const BOT_SOCKET_URL = resolveBotSocketUrl();

type EmitEvents = {
  chat_message: { message: string; conversation_id: string; profile?: string };
  reset_conversation: { conversation_id: string };
};

type ListenEvents = {
  connected: (data: { conversation_id: string }) => void;
  history: (data: { messages: Array<{ role: string; content: string }> }) => void;
  thinking_start: () => void;
  thinking_end: () => void;
  text_delta: (data: { delta?: string; text?: string }) => void;
  tool_call: (data: { toolCallId: string; toolName: string; args: Record<string, unknown>; announcement?: string }) => void;
  tool_result: (data: { toolCallId: string; result: string }) => void;
  sources: (data: { sources: Array<Record<string, unknown>> }) => void;
  state: (data: Record<string, unknown>) => void;
  finish: (data: {
    finishReason: string;
    usage: { promptTokens: number; completionTokens: number };
    suggestedActions?: Array<{ label: string; value: string }>;
  }) => void;
  chips_update: (data: { suggestedActions: Array<{ label: string; value: string }> }) => void;
  error: (data: { message: string }) => void;
  conversation_reset: (data: { conversation_id: string }) => void;
};

let _socket: Socket<ListenEvents, EmitEvents> | null = null;

function getSocket(): Socket<ListenEvents, EmitEvents> {
  if (!_socket) {
    _socket = io(BOT_SOCKET_URL, {
      transports: ["websocket"],
      autoConnect: false,
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
    });
  }
  return _socket;
}

export const socketClient = {
  connect(conversationId: string): void {
    const socket = getSocket();
    // Pass conversation_id as query param so backend can restore history
    (socket.io as any).opts.query = { conversation_id: conversationId };
    if (!socket.connected) {
      socket.connect();
    }
  },

  disconnect(): void {
    _socket?.disconnect();
  },

  emit<K extends keyof EmitEvents>(event: K, data: EmitEvents[K]): void {
    (getSocket() as any).emit(event, data);
  },

  on<K extends keyof ListenEvents>(event: K, handler: ListenEvents[K]): void {
    getSocket().on(event, handler as any);
  },

  off<K extends keyof ListenEvents>(event: K, handler?: ListenEvents[K]): void {
    if (handler) {
      getSocket().off(event, handler as any);
    } else {
      getSocket().removeAllListeners(event);
    }
  },

  onConnect(handler: () => void): void {
    getSocket().on("connect", handler);
  },

  onDisconnect(handler: (reason: string) => void): void {
    getSocket().on("disconnect", handler);
  },

  onConnectError(handler: (err: Error) => void): void {
    getSocket().on("connect_error", handler);
  },

  offConnect(handler: () => void): void {
    getSocket().off("connect", handler);
  },

  offDisconnect(handler: (reason: string) => void): void {
    getSocket().off("disconnect", handler);
  },

  offConnectError(handler: (err: Error) => void): void {
    getSocket().off("connect_error", handler);
  },

  isConnected(): boolean {
    return _socket?.connected ?? false;
  },
};
