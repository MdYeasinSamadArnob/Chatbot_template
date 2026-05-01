"use client";

import type { ChatMessage, ThinkingMessage } from "@/store/types";
import { UserMessage } from "./UserMessage";
import { AgentMessage } from "./AgentMessage";
import { ToolCallMessage } from "./ToolCallMessage";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { SourceBlocksMessage } from "./SourceBlocksMessage";

interface Props {
  message: ChatMessage;
}

/**
 * Central dispatcher — renders the correct component based on message type.
 *
 * Mirrors Metabase's MetabotChatMessage.tsx which switches on message.type
 * to render UserMessage, AgentMessage, AgentToolCallMessage, etc.
 *
 * To add a new message type:
 *   1. Add the type to store/types.ts ChatMessage union
 *   2. Create the component
 *   3. Add a case here
 */
export function MessageDispatcher({ message }: Props) {
  switch (message.type) {
    case "user_text":
      return <UserMessage message={message} />;

    case "agent_text":
      return <AgentMessage message={message} />;

    case "tool_call":
      return <ToolCallMessage message={message} />;

    case "source_blocks":
      return <SourceBlocksMessage message={message} />;

    case "thinking":
      return <ThinkingIndicator label={(message as ThinkingMessage).label} />;

    default:
      // Exhaustive check — TypeScript will flag unhandled union members
      return null;
  }
}
