import { NextRequest, NextResponse } from "next/server";

const ADMIN_API = process.env.ADMIN_API_URL ?? "http://localhost:9002";
const ADMIN_SECRET = process.env.ADMIN_SECRET ?? "";

export async function GET(
  _req: NextRequest,
  { params }: { params: { key: string } }
) {
  const res = await fetch(`${ADMIN_API}/api/flows/${params.key}`, {
    cache: "no-store",
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

export async function PUT(
  req: NextRequest,
  { params }: { params: { key: string } }
) {
  const body = await req.json();
  try {
    const res = await fetch(`${ADMIN_API}/api/flows/${params.key}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "x-admin-secret": ADMIN_SECRET,
      },
      body: JSON.stringify(body),
    });
    const text = await res.text();
    let data: unknown;
    try { data = JSON.parse(text); } catch { data = { detail: text }; }
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json({ detail: String(err) }, { status: 502 });
  }
}
