/**
 * HTML utility functions — usable in both browser and Node.js.
 *
 * htmlToMarkdown  — strips HTML to clean Markdown for LLM consumption
 * htmlToRenderBlocks — parses HTML into typed block list for UI rendering
 * extractImageUrls — collects all img src values
 */

import { parse, HTMLElement, Node, NodeType } from "node-html-parser";
import type { RenderBlock } from "@/types";
import { parseYouTubeVideoId } from "@/lib/video-utils";

// ── HTML → Markdown ────────────────────────────────────────────────────────

export function htmlToMarkdown(html: string): string {
  if (!html || html.trim() === "" || html === "<p></p>") return "";

  const root = parse(html);

  function nodeToMd(node: Node): string {
    if (node.nodeType === NodeType.TEXT_NODE) return node.text;

    const el = node as HTMLElement;
    const tag = el.tagName?.toLowerCase() ?? "";
    const inner = () => el.childNodes.map(nodeToMd).join("");

    switch (tag) {
      case "h1": return `# ${inner()}\n\n`;
      case "h2": return `## ${inner()}\n\n`;
      case "h3": return `### ${inner()}\n\n`;
      case "h4": return `#### ${inner()}\n\n`;
      case "h5": return `##### ${inner()}\n\n`;
      case "h6": return `###### ${inner()}\n\n`;
      case "p": {
        const c = inner();
        return c.trim() ? `${c}\n\n` : "";
      }
      case "br": return "\n";
      case "strong":
      case "b": return `**${inner()}**`;
      case "em":
      case "i": return `*${inner()}*`;
      case "s":
      case "del":
      case "strike": return `~~${inner()}~~`;
      case "code": {
        const parentTag = (el.parentNode as HTMLElement | null)?.tagName?.toLowerCase();
        return parentTag === "pre" ? inner() : `\`${inner()}\``;
      }
      case "pre": return `\`\`\`\n${inner()}\n\`\`\`\n\n`;
      case "blockquote": return `> ${inner().trim().replace(/\n/g, "\n> ")}\n\n`;
      case "a": return `[${inner()}](${el.getAttribute("href") ?? "#"})`;
      case "img": {
        const src = el.getAttribute("src") ?? "";
        const alt = el.getAttribute("alt") ?? "";
        return `![${alt}](${src})\n\n`;
      }
      case "iframe": {
        const src = el.getAttribute("src") ?? "";
        return src ? `[Video](${src})\n\n` : "";
      }
      case "ul": {
        const items = el
          .querySelectorAll("li")
          .map((li) => `- ${li.text.trim()}`)
          .join("\n");
        return items ? items + "\n\n" : "";
      }
      case "ol": {
        const items = el
          .querySelectorAll("li")
          .map((li, i) => `${i + 1}. ${li.text.trim()}`)
          .join("\n");
        return items ? items + "\n\n" : "";
      }
      case "li": return inner();
      case "table": {
        const headers = el.querySelectorAll("th").map((th) => th.text.trim());
        const rows = el
          .querySelectorAll("tbody tr")
          .map((tr) => tr.querySelectorAll("td").map((td) => td.text.trim()));

        let md = "";
        if (headers.length) {
          md += `| ${headers.join(" | ")} |\n`;
          md += `| ${headers.map(() => "---").join(" | ")} |\n`;
        }
        rows.forEach((row) => {
          md += `| ${row.join(" | ")} |\n`;
        });
        return md ? md + "\n" : "";
      }
      case "hr": return "---\n\n";
      case "mark": return `==${inner()}==`;
      default: return inner();
    }
  }

  return root.childNodes.map(nodeToMd).join("").trim();
}

// ── HTML → RenderBlocks ────────────────────────────────────────────────────

export function htmlToRenderBlocks(html: string): RenderBlock[] {
  if (!html || html.trim() === "" || html === "<p></p>") return [];

  const root = parse(html);
  const blocks: RenderBlock[] = [];

  function pushTextBlock(content: string): void {
    const trimmed = content.trim();
    if (trimmed) blocks.push({ type: "text", content: trimmed });
  }

  function pushImageBlock(el: HTMLElement): void {
    const url = el.getAttribute("src") ?? "";
    if (!url) return;
    blocks.push({ type: "image", url, alt: el.getAttribute("alt") ?? "" });
  }

  function pushVideoBlockFromIframe(el: HTMLElement): boolean {
    const src = el.getAttribute("src") ?? "";
    const videoId = parseYouTubeVideoId(src);
    if (!src || !videoId) return false;
    blocks.push({
      type: "video",
      provider: "youtube",
      url: src,
      video_id: videoId,
      title: el.getAttribute("title") ?? undefined,
    });
    return true;
  }

  function processMixedInlineChildren(el: HTMLElement): void {
    let textBuffer = "";

    const flushText = () => {
      pushTextBlock(textBuffer);
      textBuffer = "";
    };

    el.childNodes.forEach((child) => {
      if (child.nodeType === NodeType.TEXT_NODE) {
        textBuffer += child.text;
        return;
      }

      const childEl = child as HTMLElement;
      const childTag = childEl.tagName?.toLowerCase() ?? "";
      if (childTag === "img") {
        flushText();
        pushImageBlock(childEl);
        return;
      }
      if (childTag === "iframe") {
        flushText();
        if (!pushVideoBlockFromIframe(childEl)) {
          const src = childEl.getAttribute("src") ?? "";
          if (src) pushTextBlock(src);
        }
        return;
      }
      textBuffer += childEl.text;
    });

    flushText();
  }

  function processEl(el: HTMLElement): void {
    const tag = el.tagName?.toLowerCase() ?? "";

    if (["h1", "h2", "h3", "h4", "h5", "h6"].includes(tag)) {
      const content = el.text.trim();
      if (content)
        blocks.push({ type: "heading", level: +tag[1] as 1 | 2 | 3 | 4 | 5 | 6, content });
      return;
    }

    if (tag === "p") {
      processMixedInlineChildren(el);
      return;
    }

    if (tag === "ul") {
      const items = el
        .querySelectorAll("li")
        .map((li) => li.text.trim())
        .filter(Boolean);
      if (items.length) blocks.push({ type: "list", variant: "unordered", items });
      return;
    }

    if (tag === "ol") {
      const items = el
        .querySelectorAll("li")
        .map((li) => li.text.trim())
        .filter(Boolean);
      if (items.length) blocks.push({ type: "list", variant: "ordered", items });
      return;
    }

    if (tag === "img") {
      pushImageBlock(el);
      return;
    }

    if (tag === "iframe") {
      if (!pushVideoBlockFromIframe(el)) {
        const src = el.getAttribute("src") ?? "";
        if (src) pushTextBlock(src);
      }
      return;
    }

    if (tag === "blockquote") {
      const content = el.text.trim();
      const cls = el.getAttribute("class") ?? "";
      let variant: CalloutVariant = "info";
      if (cls.includes("warning")) variant = "warning";
      else if (cls.includes("error") || cls.includes("danger")) variant = "error";
      else if (cls.includes("success")) variant = "success";
      else if (cls.includes("tip")) variant = "tip";
      if (content) blocks.push({ type: "callout", variant, content });
      return;
    }

    if (tag === "pre") {
      const codeEl = el.querySelector("code");
      const content = (codeEl ?? el).text;
      const langClass = codeEl?.getAttribute("class") ?? "";
      const langMatch = langClass.match(/language-(\w+)/);
      blocks.push({ type: "code", content, language: langMatch?.[1] });
      return;
    }

    if (tag === "table") {
      const headers = el.querySelectorAll("th").map((th) => th.text.trim());
      const rows = el
        .querySelectorAll("tbody tr")
        .map((tr) => tr.querySelectorAll("td").map((td) => td.text.trim()))
        .filter((r) => r.length > 0);
      if (headers.length || rows.length)
        blocks.push({ type: "table", headers, rows });
      return;
    }

    if (tag === "hr") {
      blocks.push({ type: "divider" });
      return;
    }

    // Container — recurse into children
    el.childNodes.forEach((child) => {
      if ((child as HTMLElement).tagName) processEl(child as HTMLElement);
    });
  }

  root.childNodes.forEach((child) => {
    if ((child as HTMLElement).tagName) processEl(child as HTMLElement);
  });

  return blocks;
}

// ── Markdown / plain-text → HTML ──────────────────────────────────────────

/**
 * Very lightweight Markdown-to-HTML converter for the most common constructs.
 * Only used as a fallback when the DB stores plain/markdown text rather than
 * wysiwyg_html, so TipTap can render it with some formatting instead of one
 * giant flat paragraph.
 */
export function markdownToHtml(md: string): string {
  if (!md || md.trim() === "") return "";

  const lines = md.split("\n");
  const out: string[] = [];
  let inUl = false;
  let inOl = false;

  const closeList = () => {
    if (inUl) { out.push("</ul>"); inUl = false; }
    if (inOl) { out.push("</ol>"); inOl = false; }
  };

  const inlineMarkup = (s: string) =>
    s
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/__(.+?)__/g, "<strong>$1</strong>")
      .replace(/_(.+?)_/g, "<em>$1</em>")
      .replace(/`(.+?)`/g, "<code>$1</code>")
      .replace(/\[(.+?)\]\((.+?)\)/g, '<a href="$2">$1</a>');

  for (const raw of lines) {
    const line = raw.trimEnd();

    // Horizontal rule
    if (/^-{3,}$|^\*{3,}$|^_{3,}$/.test(line)) {
      closeList(); out.push("<hr>"); continue;
    }
    // Headings
    const hMatch = line.match(/^(#{1,6})\s+(.*)/);
    if (hMatch) {
      closeList();
      const level = hMatch[1].length;
      out.push(`<h${level}>${inlineMarkup(hMatch[2])}</h${level}>`);
      continue;
    }
    // Unordered list
    const ulMatch = line.match(/^[-*+]\s+(.*)/);
    if (ulMatch) {
      if (inOl) { out.push("</ol>"); inOl = false; }
      if (!inUl) { out.push("<ul>"); inUl = true; }
      out.push(`<li>${inlineMarkup(ulMatch[1])}</li>`);
      continue;
    }
    // Ordered list
    const olMatch = line.match(/^\d+\.\s+(.*)/);
    if (olMatch) {
      if (inUl) { out.push("</ul>"); inUl = false; }
      if (!inOl) { out.push("<ol>"); inOl = true; }
      out.push(`<li>${inlineMarkup(olMatch[1])}</li>`);
      continue;
    }
    // Blockquote
    const bqMatch = line.match(/^>\s?(.*)/);
    if (bqMatch) {
      closeList(); out.push(`<blockquote><p>${inlineMarkup(bqMatch[1])}</p></blockquote>`); continue;
    }
    // Blank line
    if (line.trim() === "") {
      closeList(); continue;
    }
    // Normal paragraph
    closeList();
    out.push(`<p>${inlineMarkup(line)}</p>`);
  }
  closeList();

  return out.join("\n");
}

/**
 * Normalise content from the DB into HTML that TipTap can load.
 * - wysiwyg_html / scraped_html → pass through (already HTML)
 * - markdown / text / anything else → convert via markdownToHtml
 */
export function contentToHtml(raw: string, contentType: string): string {
  if (!raw) return "";
  if (contentType === "wysiwyg_html" || contentType === "scraped_html") return raw;
  return markdownToHtml(raw);
}

// ── Extract image URLs ─────────────────────────────────────────────────────

export function extractImageUrls(html: string): string[] {
  if (!html) return [];
  return parse(html)
    .querySelectorAll("img")
    .map((img) => img.getAttribute("src") ?? "")
    .filter(Boolean);
}

type CalloutVariant = "info" | "warning" | "error" | "success" | "tip";
