import { NextRequest, NextResponse } from "next/server";
import { extractImageUrls } from "@/lib/html-utils";

const ADMIN_API_URL = process.env.ADMIN_API_URL ?? "http://localhost:9002";
const ADMIN_SECRET = process.env.ADMIN_SECRET ?? "";

function adminHeaders(method: string): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (method !== "GET" && ADMIN_SECRET) {
    headers["x-admin-secret"] = ADMIN_SECRET;
  }
  return headers;
}

export async function GET() {
  try {
    const res = await fetch(`${ADMIN_API_URL}/api/kb/documents?limit=100&offset=0`, {
      method: "GET",
      headers: adminHeaders("GET"),
      cache: "no-store",
    });

    const payload = await res.json();
    if (!res.ok) {
      return NextResponse.json(payload, { status: res.status });
    }

    const items = Array.isArray(payload?.items) ? payload.items : [];
    const mapped = items.map((doc: any) => ({
      id: doc.id,
      title: doc.title,
      category: doc.category,
      subcategory: doc.subcategory ?? "",
      intent_tags: doc.intent_tags ?? [],
      version: doc.version ?? 1,
      author: doc.author ?? "",
      is_published: !!doc.is_published,
      embedding_status: doc.embedding_status ?? null,
      embedded_at: doc.embedded_at ?? null,
      created_at: doc.created_at,
      updated_at: doc.updated_at,
      document_type: "article",
      content_type: "markdown",
      content_raw: "",
      content_text: "",
      image_urls: [],
      render_blocks: [],
      language: "en",
      source_url: "",
      relevance_score: null,
    }));

    return NextResponse.json(mapped);
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const contentRaw = typeof body.content_raw === "string" ? body.content_raw : "";

    const createPayload = {
      title: body.title,
      category: body.category ?? "general",
      subcategory: body.subcategory || null,
      intent_tags: Array.isArray(body.intent_tags) ? body.intent_tags : [],
      author: body.author || null,
      is_published: body.is_published ?? true,
      content: contentRaw,
      source_url: body.source_url || null,
      image_urls: extractImageUrls(contentRaw),
      language: body.language ?? "en",
    };

    const res = await fetch(`${ADMIN_API_URL}/api/kb/documents`, {
      method: "POST",
      headers: adminHeaders("POST"),
      body: JSON.stringify(createPayload),
    });

    const payload = await res.json();
    if (!res.ok) {
      return NextResponse.json(payload, { status: res.status });
    }

    return NextResponse.json({ id: payload.id }, { status: 201 });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
