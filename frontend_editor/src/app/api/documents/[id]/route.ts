import { NextRequest, NextResponse } from "next/server";
import { query, ensureSchema } from "@/lib/db";
import { htmlToMarkdown, htmlToRenderBlocks, extractImageUrls } from "@/lib/html-utils";
import { generateEmbedding } from "@/lib/embeddings";

interface RouteContext {
  params: { id: string };
}

export async function GET(_req: NextRequest, { params }: RouteContext) {
  try {
    await ensureSchema();

    const rows = await query(
      `SELECT
        d.id, d.title, d.category, d.subcategory, d.intent_tags,
        d.version, d.author, d.is_published, d.created_at, d.updated_at,
        c.id AS chunk_id, c.document_type, c.content_type,
        -- Prefer content_raw; fall back to content_text for markdown-typed chunks
        COALESCE(NULLIF(c.content_raw, ''), c.content_text) AS content_raw,
        c.content_text, c.image_urls, c.render_blocks,
        c.language, c.source_url, c.relevance_score
       FROM knowledge_documents d
       LEFT JOIN LATERAL (
         SELECT * FROM knowledge_chunks
         WHERE document_id = d.id AND is_active = TRUE
         ORDER BY chunk_index ASC
         LIMIT 1
       ) c ON TRUE
       WHERE d.id = $1`,
      [params.id]
    );

    const row = rows[0];
    if (!row) return NextResponse.json({ error: "Not found" }, { status: 404 });
    return NextResponse.json(row);
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function PUT(req: NextRequest, { params }: RouteContext) {
  try {
    await ensureSchema();

    const body = await req.json();
    const {
      title,
      category = "general",
      subcategory = null,
      intent_tags = [],
      document_type = "faq",
      content_type = "wysiwyg_html",
      language = "en",
      author = null,
      is_published = true,
      source_url = null,
      relevance_score = null,
      content_raw = "",
    } = body;

    if (!title?.trim()) {
      return NextResponse.json({ error: "title is required" }, { status: 400 });
    }

    const content_text = htmlToMarkdown(content_raw);
    const render_blocks = htmlToRenderBlocks(content_raw);
    const image_urls = extractImageUrls(content_raw);

    const [doc] = await query(
      `UPDATE knowledge_documents
       SET title=$1, category=$2, subcategory=$3, intent_tags=$4,
           author=$5, is_published=$6, version=version+1, updated_at=NOW()
       WHERE id=$7
       RETURNING *`,
      [title.trim(), category, subcategory, intent_tags, author, is_published, params.id]
    );

    if (!doc) return NextResponse.json({ error: "Not found" }, { status: 404 });

    // Replace chunk (delete old, insert fresh)
    await query(`DELETE FROM knowledge_chunks WHERE document_id = $1`, [params.id]);

    await query(
      `INSERT INTO knowledge_chunks
         (document_id, document_title, document_type, content_text, content_type,
          content_raw, image_urls, render_blocks, chunk_index, chunk_total,
          source_url, language, is_active, relevance_score)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,0,1,$9,$10,TRUE,$11)`,
      [
        params.id,
        title.trim(),
        document_type,
        content_text,
        content_type,
        content_raw,
        image_urls,
        JSON.stringify(render_blocks),
        source_url,
        language,
        relevance_score ?? null,
      ]
    );

    // Generate and store embedding (best-effort — failure doesn't block save)
    const embedding = await generateEmbedding(content_text);
    if (embedding) {
      const vecStr = "[" + embedding.join(",") + "]";
      await query(
        `UPDATE knowledge_chunks SET chunk_embedding = $1::vector
         WHERE document_id = $2 ORDER BY chunk_index ASC LIMIT 1`,
        [vecStr, params.id]
      ).catch(() => {});
    }

    return NextResponse.json(doc);
  } catch (err) {
    console.error("PUT /api/documents/[id]:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function DELETE(_req: NextRequest, { params }: RouteContext) {
  try {
    await ensureSchema();

    await query(
      `UPDATE knowledge_documents
       SET is_published = FALSE, updated_at = NOW()
       WHERE id = $1`,
      [params.id]
    );
    await query(
      `UPDATE knowledge_chunks SET is_active = FALSE WHERE document_id = $1`,
      [params.id]
    );

    return NextResponse.json({ success: true });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
