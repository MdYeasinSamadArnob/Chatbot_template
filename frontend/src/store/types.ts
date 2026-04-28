/**
 * TypeScript type definitions for the Bank Help Bot chat system.
 */

// ── Message types ──────────────────────────────────────────────────────────

export type MessageType = "user_text" | "agent_text" | "tool_call" | "thinking";

interface BaseMessage {
  id: string;
  type: MessageType;
  timestamp: number;
}

export interface UserTextMessage extends BaseMessage {
  type: "user_text";
  text: string;
}

export interface AgentTextMessage extends BaseMessage {
  type: "agent_text";
  /** Text accumulates as deltas arrive from text_delta socket events. */
  text: string;
  /** True while tokens are still streaming in from the backend. */
  streaming?: boolean;
}

export interface ToolCallMessage extends BaseMessage {
  type: "tool_call";
  toolCallId: string;
  /** Human-readable text to show while the tool is running. */
  announcement?: string;
  toolName: string;
  args: Record<string, unknown>;
  result?: string;
  status: "running" | "done" | "error";
}

export interface ThinkingMessage extends BaseMessage {
  type: "thinking";
}

export type ChatMessage =
  | UserTextMessage
  | AgentTextMessage
  | ToolCallMessage
  | ThinkingMessage;
// ── Quick replies ─────────────────────────────────────────────────────────────

export interface SuggestedAction {
  label: string;
  value: string;
}
// ── Connection state ───────────────────────────────────────────────────────

export type ConnectionStatus = "connected" | "disconnected" | "reconnecting";

// ── Session state ──────────────────────────────────────────────────────────

export interface SessionState {
  todos: string[];
  notes: Record<string, string>;
  context: Record<string, unknown>;
}

// ── Stream callbacks (kept for SSE fallback compatibility) ─────────────────

export interface StreamCallbacks {
  onTextPart: (text: string) => void;
  onToolCallPart: (toolCallId: string, toolName: string, args: Record<string, unknown>) => void;
  onToolResultPart: (toolCallId: string, result: string) => void;
  onDataPart: (type: string, data: unknown) => void;
  onErrorPart: (error: string) => void;
  onFinishPart: (finishReason: string, usage: { promptTokens: number; completionTokens: number }) => void;
}

// ── Zustand store shape ────────────────────────────────────────────────────

export interface ChatStore {
  // State
  messages: ChatMessage[];
  isProcessing: boolean;
  conversationId: string;
  sessionState: SessionState;
  errorMessages: string[];
  connectionStatus: ConnectionStatus;
  /** Quick-reply chips driven by the backend. Cleared when user sends a message. */
  suggestedActions: SuggestedAction[];

  // Actions
  addUserMessage: (text: string) => void;
  addAgentTextDelta: (delta: string) => void;
  finishStreaming: () => void;
  toolCallStart: (toolCallId: string, toolName: string, args: Record<string, unknown>, announcement?: string) => void;
  toolCallEnd: (toolCallId: string, result: string) => void;
  updateSessionState: (state: SessionState) => void;
  setProcessing: (processing: boolean) => void;
  addErrorMessage: (error: string) => void;
  addThinking: () => void;
  removeThinking: () => void;
  setConnectionStatus: (status: ConnectionStatus) => void;
  loadHistory: (messages: Array<{ role: string; content: string }>) => void;
  resetConversation: () => void;
  setSuggestedActions: (actions: SuggestedAction[]) => void;
}

