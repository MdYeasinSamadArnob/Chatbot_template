const YOUTUBE_HOSTS = new Set([
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "youtu.be",
  "www.youtu.be",
  "youtube-nocookie.com",
  "www.youtube-nocookie.com",
]);

function tryParseUrl(input: string): URL | null {
  try {
    const url = new URL(input.trim());
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    return url;
  } catch {
    return null;
  }
}

function parseTimestampToSeconds(raw: string | null): number | null {
  if (!raw) return null;
  const value = raw.trim().toLowerCase();
  if (!value) return null;

  if (/^\d+$/.test(value)) return Number(value);

  const match = value.match(/^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/);
  if (!match) return null;
  const hours = Number(match[1] ?? 0);
  const minutes = Number(match[2] ?? 0);
  const seconds = Number(match[3] ?? 0);
  return hours * 3600 + minutes * 60 + seconds;
}

export function parseYouTubeVideoId(input: string): string | null {
  const parsed = tryParseUrl(input);
  if (!parsed) return null;
  if (!YOUTUBE_HOSTS.has(parsed.hostname.toLowerCase())) return null;

  const host = parsed.hostname.toLowerCase();
  const path = parsed.pathname;

  if (host.includes("youtu.be")) {
    const id = path.replace(/^\//, "").split("/")[0];
    return id || null;
  }

  if (path === "/watch") {
    const id = parsed.searchParams.get("v");
    return id || null;
  }

  if (path.startsWith("/shorts/")) {
    const id = path.split("/")[2];
    return id || null;
  }

  if (path.startsWith("/embed/")) {
    const id = path.split("/")[2];
    return id || null;
  }

  return null;
}

export function toYouTubeEmbedUrl(input: string): string | null {
  const parsed = tryParseUrl(input);
  if (!parsed) return null;

  const videoId = parseYouTubeVideoId(input);
  if (!videoId) return null;

  const t = parseTimestampToSeconds(parsed.searchParams.get("t") ?? parsed.searchParams.get("start"));
  const embed = new URL(`https://www.youtube-nocookie.com/embed/${videoId}`);
  if (t && t > 0) embed.searchParams.set("start", String(t));

  return embed.toString();
}
