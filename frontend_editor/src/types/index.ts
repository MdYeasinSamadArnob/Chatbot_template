// ── Document layer ─────────────────────────────────────────────────────────

export interface KBDocument {
  id: string;
  title: string;
  category: string;
  subcategory?: string | null;
  intent_tags: string[];
  version: number;
  author?: string | null;
  is_published: boolean;
  created_at: string;
  updated_at: string;
  // Joined from knowledge_chunks (first chunk)
  chunk_id?: string;
  document_type?: string;
  content_text?: string;
  content_raw?: string;
  content_type?: string;
  image_urls?: string[];
  render_blocks?: RenderBlock[];
  language?: string;
  source_url?: string | null;
  relevance_score?: number | null;
}

export interface DocumentMetadata {
  title: string;
  category: string;
  subcategory: string;
  document_type: string;
  content_type: string;
  language: string;
  intent_tags: string[];
  author: string;
  is_published: boolean;
  source_url: string;
  relevance_score: number | null;
}

// ── Render blocks ──────────────────────────────────────────────────────────

export type RenderBlock =
  | TextBlock
  | HeadingBlock
  | ListBlock
  | ImageBlock
  | CalloutBlock
  | CodeBlock
  | TableBlock
  | DividerBlock;

export interface TextBlock {
  type: "text";
  content: string;
}

export interface HeadingBlock {
  type: "heading";
  level: 1 | 2 | 3 | 4 | 5 | 6;
  content: string;
}

export interface ListBlock {
  type: "list";
  variant: "ordered" | "unordered";
  items: string[];
}

export interface ImageBlock {
  type: "image";
  url: string;
  alt: string;
}

export interface CalloutBlock {
  type: "callout";
  variant: "info" | "warning" | "error" | "success" | "tip";
  content: string;
}

export interface CodeBlock {
  type: "code";
  content: string;
  language?: string;
}

export interface TableBlock {
  type: "table";
  headers: string[];
  rows: string[][];
}

export interface DividerBlock {
  type: "divider";
}
