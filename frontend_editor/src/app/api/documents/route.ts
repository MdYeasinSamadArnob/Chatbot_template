import { NextRequest, NextResponse } from "next/server";
import { v4 as uuidv4 } from "uuid";
import { query, ensureSchema } from "@/lib/db";
import { htmlToMarkdown, htmlToRenderBlocks, extractImageUrls } from "@/lib/html-utils";
import { generateEmbedding } from "@/lib/embeddings";

export async function GET() {
  try {
    await ensureSchema();

    const rows = await query(`
      SELECT
        d.id, d.title, d.category, d.subcategory, d.intent_tags,
        d.version, d.author, d.is_published, d.embedding_status, d.embedded_at,
        d.created_at, d.updated_at,
        c.id           AS chunk_id,
        c.document_type,
        c.content_type,
        COALESCE(NULLIF(c.content_raw, ''), c.content_text) AS content_raw,
        c.content_text,
        c.image_urls,
        c.render_blocks,
        c.language,
        c.source_url,
        c.relevance_score
      FROM knowledge_documents d
      LEFT JOIN LATERAL (
        SELECT * FROM knowledge_chunks
        WHERE document_id = d.id AND is_active = TRUE
        ORDER BY chunk_index ASC
        LIMIT 1
      ) c ON TRUE
      ORDER BY d.updated_at DESC
      LIMIT 200
    `);

    return NextResponse.json(rows);
  } catch (err) {
    console.error("GET /api/documents:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
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
    const docId = uuidv4();

    const [doc] = await query(
      `INSERT INTO knowledge_documents
         (id, title, category, subcategory, intent_tags, author, is_published)
       VALUES ($1,$2,$3,$4,$5,$6,$7)
       RETURNING *`,
      [docId, title.trim(), category, subcategory, intent_tags, author, is_published]
    );

    await query(
      `INSERT INTO knowledge_chunks
         (document_id, document_title, document_type, content_text, content_type,
          content_raw, image_urls, render_blocks, chunk_index, chunk_total,
          source_url, language, is_active, relevance_score)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,0,1,$9,$10,TRUE,$11)`,
      [
        docId,
        title.trim(),
        document_type,
        content_text,
        content_type,
        content_raw,
        image_urls,
        JSON.stringify(render_blocks),
        source_url,
        language,
        relevance_score,
      ]
    );

    await query(
      `UPDATE knowledge_documents
       SET embedding_status = 'processing', embedded_at = NULL, updated_at = NOW()
       WHERE id = $1`,
      [docId]
    ).catch((err) => {
      console.warn("POST /api/documents: embedding_status processing update skipped:", err);
    });

    // Generate and store embedding (best-effort — failure doesn't block save)
    const embedding = await generateEmbedding(content_text);
    if (embedding) {
      const vecStr = "[" + embedding.join(",") + "]";
      await query(
        `UPDATE knowledge_chunks
         SET chunk_embedding = $1::vector
         WHERE id = (
           SELECT id
           FROM knowledge_chunks
           WHERE document_id = $2 AND is_active = TRUE
           ORDER BY chunk_index ASC
           LIMIT 1
         )`,
        [vecStr, docId]
      ).catch((err) => {
        console.error("POST /api/documents embedding update failed:", err);
      });

      await query(
        `UPDATE knowledge_documents
         SET embedding_status = 'ready', embedded_at = NOW(), updated_at = NOW()
         WHERE id = $1`,
        [docId]
      ).catch((err) => {
        console.warn("POST /api/documents: embedding_status ready update skipped:", err);
      });
    } else {
      await query(
        `UPDATE knowledge_documents
         SET embedding_status = 'failed', updated_at = NOW()
         WHERE id = $1`,
        [docId]
      ).catch((err) => {
        console.warn("POST /api/documents: embedding_status failed update skipped:", err);
      });
    }

    return NextResponse.json(doc, { status: 201 });
  } catch (err) {
    console.error("POST /api/documents:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
