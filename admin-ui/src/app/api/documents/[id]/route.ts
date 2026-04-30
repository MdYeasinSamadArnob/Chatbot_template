import { NextRequest, NextResponse } from "next/server";
import { extractImageUrls } from "@/lib/html-utils";

interface RouteContext {
  params: { id: string };
}

const ADMIN_API_URL = process.env.ADMIN_API_URL ?? "http://localhost:9002";
const ADMIN_SECRET = process.env.ADMIN_SECRET ?? "";

function adminHeaders(method: string): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (method !== "GET" && ADMIN_SECRET) {
    headers["x-admin-secret"] = ADMIN_SECRET;
  }
  return headers;
}

async function fetchDocument(id: string): Promise<Response> {
  return fetch(`${ADMIN_API_URL}/api/kb/documents/${id}`, {
    method: "GET",
    headers: adminHeaders("GET"),
    cache: "no-store",
  });
}

function mapDocumentPayload(payload: any) {
  const doc = payload?.document ?? {};
  const chunks = Array.isArray(payload?.chunks) ? payload.chunks : [];
  const combinedText = chunks
    .map((chunk: any) => (typeof chunk?.content_text === "string" ? chunk.content_text.trim() : ""))
    .filter(Boolean)
    .join("\n\n");
  const firstChunk = chunks[0] ?? {};

  return {
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
    chunk_id: firstChunk.id,
    document_type: firstChunk.document_type ?? "article",
    content_type: "markdown",
    content_raw: combinedText,
    content_text: combinedText,
    image_urls: firstChunk.image_urls ?? [],
    render_blocks: [],
    language: firstChunk.language ?? "en",
    source_url: firstChunk.source_url ?? "",
    relevance_score: firstChunk.relevance_score ?? null,
  };
}

export async function GET(_req: NextRequest, { params }: RouteContext) {
  try {
    const res = await fetchDocument(params.id);
    const payload = await res.json();
    if (!res.ok) {
      return NextResponse.json(payload, { status: res.status });
    }
    return NextResponse.json(mapDocumentPayload(payload));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function PUT(req: NextRequest, { params }: RouteContext) {
  try {
    const body = await req.json();
    const contentRaw = typeof body.content_raw === "string" ? body.content_raw : "";

    const metadataPayload = {
      title: body.title,
      category: body.category ?? "general",
      subcategory: body.subcategory || null,
      intent_tags: Array.isArray(body.intent_tags) ? body.intent_tags : [],
      author: body.author || null,
      is_published: body.is_published ?? true,
    };

    const metaRes = await fetch(`${ADMIN_API_URL}/api/kb/documents/${params.id}`, {
      method: "PUT",
      headers: adminHeaders("PUT"),
      body: JSON.stringify(metadataPayload),
    });

    if (!metaRes.ok) {
      const payload = await metaRes.json();
      return NextResponse.json(payload, { status: metaRes.status });
    }

    const contentPayload = {
      content: contentRaw,
      source_url: body.source_url || null,
      image_urls: extractImageUrls(contentRaw),
      language: body.language ?? "en",
    };

    const contentRes = await fetch(`${ADMIN_API_URL}/api/kb/documents/${params.id}/content`, {
      method: "POST",
      headers: adminHeaders("POST"),
      body: JSON.stringify(contentPayload),
    });

    if (!contentRes.ok) {
      const payload = await contentRes.json();
      return NextResponse.json(payload, { status: contentRes.status });
    }

    const finalRes = await fetchDocument(params.id);
    const finalPayload = await finalRes.json();
    if (!finalRes.ok) {
      return NextResponse.json(finalPayload, { status: finalRes.status });
    }

    return NextResponse.json(mapDocumentPayload(finalPayload));
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function DELETE(_req: NextRequest, { params }: RouteContext) {
  try {
    const res = await fetch(`${ADMIN_API_URL}/api/kb/documents/${params.id}`, {
      method: "DELETE",
      headers: adminHeaders("DELETE"),
    });

    if (!res.ok) {
      const payload = await res.json();
      return NextResponse.json(payload, { status: res.status });
    }

    return NextResponse.json({ success: true });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
