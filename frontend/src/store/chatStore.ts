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
  ToolCallMessage,
  UserTextMessage,
  ThinkingMessage,
} from "./types";

const THINKING_ID = "__thinking__";

const defaultSessionState = (): SessionState => ({
  todos: [],
  notes: {},
  context: {},
});

export const useChatStore = create<ChatStore>((set, get) => ({
  // â”€â”€ Initial state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  messages: [],
  isProcessing: false,
  conversationId: crypto.randomUUID(),
  sessionState: defaultSessionState(),
  errorMessages: [],
  connectionStatus: "disconnected",

  // â”€â”€ Actions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  addUserMessage: (text: string) =>
    set((state) => {
      const msg: UserTextMessage = {
        id: crypto.randomUUID(),
        type: "user_text",
        text,
        timestamp: Date.now(),
      };
      return { messages: [...state.messages, msg], errorMessages: [] };
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
        id: crypto.randomUUID(),
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

  toolCallStart: (toolCallId, toolName, args) =>
    set((state) => {
      const msg: ToolCallMessage = {
        id: toolCallId,
        type: "tool_call",
        toolCallId,
        toolName,
        args,
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
              id: crypto.randomUUID(),
              type: "user_text",
              text: m.content,
              timestamp: Date.now(),
            } as UserTextMessage;
          }
          return {
            id: crypto.randomUUID(),
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
      conversationId: crypto.randomUUID(),
      sessionState: defaultSessionState(),
      errorMessages: [],
    }),
}));
