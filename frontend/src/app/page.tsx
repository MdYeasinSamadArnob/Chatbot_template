import { Suspense } from "react";
import { ChatScreen } from "@/components/chat/ChatScreen";

/**
 * Banking Help Bot - full-screen webview entry point.
 *
 * The Android app injects the conversation ID as a URL query parameter:
 *   ?conversation_id=<uuid>
 *
 * `ChatScreen` reads it via `useSearchParams()` internally.
 */
export default function Home() {
  return (
    <Suspense fallback={null}>
      <ChatScreen />
    </Suspense>
  );
}
