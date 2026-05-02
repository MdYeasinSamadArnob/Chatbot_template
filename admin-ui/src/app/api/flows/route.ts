import { NextRequest, NextResponse } from "next/server";

const ADMIN_API = process.env.ADMIN_API_URL ?? "http://localhost:9002";

export async function GET() {
  const res = await fetch(`${ADMIN_API}/api/flows`, { cache: "no-store" });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
