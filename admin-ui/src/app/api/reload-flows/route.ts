import { NextResponse } from "next/server";

const BOT_SOCKET_URL = process.env.BOT_SOCKET_URL ?? "http://localhost:9001";
const BOT_ADMIN_SECRET = process.env.BOT_ADMIN_SECRET ?? "";

export async function POST() {
  try {
    const res = await fetch(`${BOT_SOCKET_URL}/admin/reload-flows`, {
      method: "POST",
      headers: {
        "Content-Length": "0",
        "x-admin-secret": BOT_ADMIN_SECRET,
      },
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    return NextResponse.json(
      { detail: String(err) },
      { status: 502 }
    );
  }
}
