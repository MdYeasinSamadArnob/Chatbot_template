/**
 * Server-side embedding helper.
 * Calls the Ollama /api/embeddings endpoint and updates the chunk row.
 * If the embedding service is unavailable the chunk is saved without a vector
 * (the search tool falls back to text search in that case).
 */

const OLLAMA_URL =
  process.env.OLLAMA_BASE_URL ?? "http://10.11.200.109:11434";
const EMBED_MODEL =
  process.env.EMBEDDING_MODEL ?? "snowflake-arctic-embed2:latest";

export async function generateEmbedding(text: string): Promise<number[] | null> {
  try {
    const res = await fetch(`${OLLAMA_URL}/api/embeddings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: EMBED_MODEL, prompt: text }),
      signal: AbortSignal.timeout(30_000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.embedding as number[];
  } catch {
    return null;
  }
}
