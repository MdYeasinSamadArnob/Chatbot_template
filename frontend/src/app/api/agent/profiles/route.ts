/**
 * Next.js API Route — proxy for agent profiles endpoint.
 */

import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:9001";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/agent/profiles`);
    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json(
      { error: `Backend unreachable: ${(err as Error).message}` },
      { status: 503 }
    );
  }
}
