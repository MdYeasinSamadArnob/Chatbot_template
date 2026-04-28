/**
 * Catch-all Next.js API route that proxies all /api/kb/* requests to the backend.
 *
 * GET requests are forwarded without an admin secret (public endpoints).
 * Non-GET requests inject the server-side ADMIN_SECRET header so the browser
 * bundle never contains the secret.
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:9001";
const ADMIN_SECRET = process.env.ADMIN_SECRET ?? "";

async function handler(
  req: NextRequest,
  { params }: { params: { proxy: string[] } }
): Promise<NextResponse> {
  const path = params.proxy.join("/");
  const search = req.nextUrl.search ?? "";
  const targetUrl = `${BACKEND_URL}/api/kb/${path}${search}`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  // Inject admin secret server-side on mutating requests
  if (req.method !== "GET" && ADMIN_SECRET) {
    headers["x-admin-secret"] = ADMIN_SECRET;
  }

  let body: string | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    try {
      body = await req.text();
    } catch {
      body = undefined;
    }
  }

  const backendRes = await fetch(targetUrl, {
    method: req.method,
    headers,
    body,
  });

  const data = await backendRes.text();
  return new NextResponse(data, {
    status: backendRes.status,
    headers: {
      "Content-Type": backendRes.headers.get("Content-Type") ?? "application/json",
    },
  });
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
