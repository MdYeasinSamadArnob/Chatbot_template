/**
 * Next.js server-side proxy for the admin-api image upload endpoint.
 *
 * POST /api/upload
 *   Forwards multipart/form-data to the admin-api, injecting the admin
 *   secret from the server-side environment variable.  This keeps the
 *   secret out of the browser bundle.
 *
 * Returns the same JSON that admin-api returns:
 *   { url: "/uploads/YYYY/MM/<uuid>.<ext>", filename: "<uuid>.<ext>" }
 */
import { NextRequest, NextResponse } from "next/server";

const ADMIN_API_URL = process.env.ADMIN_API_URL ?? "http://localhost:9002";
const ADMIN_SECRET = process.env.ADMIN_SECRET ?? "";

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData();

    const res = await fetch(`${ADMIN_API_URL}/api/upload`, {
      method: "POST",
      headers: {
        "x-admin-secret": ADMIN_SECRET,
        // Do NOT set Content-Type here — fetch sets it automatically with the
        // correct multipart boundary when given a FormData body.
      },
      body: formData,
    });

    const payload = await res.json();
    return NextResponse.json(payload, { status: res.status });
  } catch (err) {
    console.error("[/api/upload proxy] error:", err);
    return NextResponse.json({ detail: "Upload failed" }, { status: 500 });
  }
}
