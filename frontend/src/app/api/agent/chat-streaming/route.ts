/**
 * Next.js API Route — proxies streaming chat requests to the Python backend.
 *
 * Why a proxy instead of direct frontend→backend calls?
 *   - No browser CORS issues
 *   - Single origin for auth middleware (JWT, cookies) in the future
 *   - Can add rate limiting, logging, request validation here
 *
 * This route preserves the streaming body intact, forwarding the AI SDK v4
 * line-protocol SSE directly to the browser.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.text();

  let backendRes: Response;
  try {
    backendRes = await fetch(`${BACKEND_URL}/api/agent/chat-streaming`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
  } catch (err) {
    return NextResponse.json(
      { error: `Backend unreachable: ${(err as Error).message}` },
      { status: 503 }
    );
  }

  if (!backendRes.ok) {
    const text = await backendRes.text();
    return NextResponse.json(
      { error: `Backend error ${backendRes.status}: ${text}` },
      { status: backendRes.status }
    );
  }

  // Stream the response body directly to the client
  return new Response(backendRes.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
      "X-Conversation-Id":
        backendRes.headers.get("X-Conversation-Id") ?? "",
    },
  });
}
