/**
 * Global chat state â€” Zustand store for Bank Help Bot.
 */

import { create } from "zustand";
import type {
  AgentTextMessage,
  ChatMessage,
  ChatStore,
  ConnectionStatus,
  SessionState,
  SuggestedAction,
  ToolCallMessage,
  UserTextMessage,
  ThinkingMessage,
} from "./types";

const THINKING_ID = "__thinking__";

function createId(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (c?.randomUUID) return c.randomUUID();

  if (c?.getRandomValues) {
    const bytes = new Uint8Array(16);
    c.getRandomValues(bytes);
    // RFC 4122 variant/version bits
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  // Last-resort fallback for older/insecure browser contexts
  return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const defaultSessionState = (): SessionState => ({
  todos: [],
  notes: {},
  context: {},
});

export const useChatStore = create<ChatStore>((set, get) => ({
  // â”€â”€ Initial state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  messages: [],
  isProcessing: false,
  conversationId: createId(),
  sessionState: defaultSessionState(),
  errorMessages: [],
  connectionStatus: "disconnected",
  suggestedActions: [],
  pendingSources: [],

  // â”€â”€ Actions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  addUserMessage: (text: string) =>
    set((state) => {
      const msg: UserTextMessage = {
        id: createId(),
        type: "user_text",
        text,
        timestamp: Date.now(),
      };
      // Clear quick-replies when user sends a message
      return {
        messages: [...state.messages, msg],
        errorMessages: [],
        suggestedActions: [],
        pendingSources: [],
      };
    }),

  addAgentTextDelta: (delta: string) =>
    set((state) => {
      const messages = state.messages;
      const last = messages[messages.length - 1];

      if (last && last.type === "agent_text") {
        return {
          messages: [
            ...messages.slice(0, -1),
            { ...last, text: last.text + delta, streaming: true } as AgentTextMessage,
          ],
        };
      }

      const newMsg: AgentTextMessage = {
        id: createId(),
        type: "agent_text",
        text: delta,
        streaming: true,
        timestamp: Date.now(),
      };
      return { messages: [...state.messages, newMsg] };
    }),

  finishStreaming: () =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.type === "agent_text" ? ({ ...m, streaming: false } as AgentTextMessage) : m
      ),
    })),

  toolCallStart: (toolCallId, toolName, args, announcement?) =>
    set((state) => {
      const msg: ToolCallMessage = {
        id: toolCallId,
        type: "tool_call",
        toolCallId,
        toolName,
        args,
        announcement,
        status: "running",
        timestamp: Date.now(),
      };
      return { messages: [...state.messages, msg] };
    }),

  toolCallEnd: (toolCallId, _result) =>
    set((state) => ({
      // Remove the tool-call pill once it completes — users only see the final answer
      messages: state.messages.filter(
        (m) => !(m.type === "tool_call" && m.toolCallId === toolCallId)
      ),
    })),

  updateSessionState: (sessionState: SessionState) => set({ sessionState }),

  setProcessing: (isProcessing: boolean) => set({ isProcessing }),

  addErrorMessage: (error: string) =>
    set((state) => ({
      errorMessages: [...state.errorMessages, error],
    })),

  addThinking: () =>
    set((state) => {
      if (state.messages.some((m) => m.id === THINKING_ID)) return state;
      const msg: ThinkingMessage = {
        id: THINKING_ID,
        type: "thinking",
        timestamp: Date.now(),
      };
      return { messages: [...state.messages, msg] };
    }),

  removeThinking: () =>
    set((state) => ({
      messages: state.messages.filter((m) => m.id !== THINKING_ID),
    })),

  updateThinkingLabel: (label: string) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === THINKING_ID && m.type === "thinking"
          ? ({ ...m, label } as ThinkingMessage)
          : m
      ),
    })),

  setConnectionStatus: (status: ConnectionStatus) =>
    set({ connectionStatus: status }),

  /** Replay conversation history received from backend on connect. */
  loadHistory: (messages) =>
    set(() => {
      const chatMessages: ChatMessage[] = messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => {
          if (m.role === "user") {
            return {
              id: createId(),
              type: "user_text",
              text: m.content,
              timestamp: Date.now(),
            } as UserTextMessage;
          }
          return {
            id: createId(),
            type: "agent_text",
            text: m.content,
            timestamp: Date.now(),
          } as AgentTextMessage;
        });
      return { messages: chatMessages };
    }),

  resetConversation: () =>
    set({
      messages: [],
      isProcessing: false,
      conversationId: createId(),
      sessionState: defaultSessionState(),
      errorMessages: [],
      suggestedActions: [],
      pendingSources: [],
    }),

  setSuggestedActions: (actions: SuggestedAction[]) =>
    set({ suggestedActions: actions }),

  setPendingSources: (sources) =>
    set({ pendingSources: Array.isArray(sources) ? sources : [] }),

  commitPendingSources: () =>
    set((state) => {
      if (!state.pendingSources.length) return state;
      const msg = {
        id: createId(),
        type: "source_blocks" as const,
        timestamp: Date.now(),
        sources: state.pendingSources,
      };
      return {
        messages: [...state.messages, msg],
        pendingSources: [],
      };
    }),
}));
