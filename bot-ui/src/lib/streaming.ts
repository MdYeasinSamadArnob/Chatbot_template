/**
 * AI SDK v4 line-protocol stream parser.
 *
 * Exact port of Metabase's frontend/src/metabase/api/ai-streaming/process-stream.ts
 *
 * Line format (each SSE data line is one of):
 *   0:"text"                    — text delta
 *   9:{toolCallId,toolName,args} — tool call
 *   a:{toolCallId,result}        — tool result
 *   2:[{type,data}]              — structured data part (state, navigate, etc.)
 *   3:"error"                   — error
 *   d:{finishReason,usage}       — finish
 */

import type { StreamCallbacks } from "@/store/types";

/**
 * Consume a streaming fetch Response and dispatch typed callbacks for
 * each AI SDK v4 line-protocol part.
 *
 * @param response  A fetch Response with a readable body (text/event-stream).
 * @param callbacks Object of typed handlers (see StreamCallbacks).
 */
export async function processStream(
  response: Response,
  callbacks: StreamCallbacks
): Promise<void> {
  if (!response.body) {
    callbacks.onErrorPart("Response has no body");
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Split on newlines — each complete line is one protocol part
      const lines = buffer.split("\n");
      // Keep the last (possibly incomplete) chunk in the buffer
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        const colonIdx = trimmed.indexOf(":");
        if (colonIdx === -1) continue;

        const prefix = trimmed.slice(0, colonIdx);
        const payload = trimmed.slice(colonIdx + 1);

        try {
          switch (prefix) {
            case "0": {
              // Text delta
              const text = JSON.parse(payload) as string;
              callbacks.onTextPart(text);
              break;
            }

            case "9": {
              // Tool call notification
              const { toolCallId, toolName, args } = JSON.parse(payload) as {
                toolCallId: string;
                toolName: string;
                args: Record<string, unknown>;
              };
              callbacks.onToolCallPart(toolCallId, toolName, args);
              break;
            }

            case "a": {
              // Tool result
              const { toolCallId, result } = JSON.parse(payload) as {
                toolCallId: string;
                result: string;
              };
              callbacks.onToolResultPart(toolCallId, result);
              break;
            }

            case "2": {
              // Structured data array — may contain multiple items
              const dataArray = JSON.parse(payload) as Array<{
                type: string;
                data: unknown;
              }>;
              for (const item of dataArray) {
                callbacks.onDataPart(item.type, item.data);
              }
              break;
            }

            case "3": {
              // Error
              const errorMsg = JSON.parse(payload) as string;
              callbacks.onErrorPart(errorMsg);
              break;
            }

            case "d": {
              // Finish — includes usage stats
              const { finishReason, usage } = JSON.parse(payload) as {
                finishReason: string;
                usage: { promptTokens: number; completionTokens: number };
              };
              callbacks.onFinishPart(finishReason, usage);
              break;
            }

            default:
              // Unknown prefix — ignore (forward compatibility)
              break;
          }
        } catch (parseError) {
          console.warn("[processStream] failed to parse line:", trimmed, parseError);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
