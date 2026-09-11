// Thin client for the dev-only Claude proxy (see vite.config.ts). Never
// calls Anthropic directly — that would mean shipping the API key to the
// browser. Returns null on any failure (no key configured, network error,
// rate limit, etc.) so callers can fall back to a template; the demo never
// hard-fails just because the LLM call didn't work.

export async function generateWithClaude(prompt: string, maxTokens = 700): Promise<string | null> {
  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, max_tokens: maxTokens }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    const content = typeof data.content === 'string' ? data.content.trim() : '';
    return content || null;
  } catch {
    return null;
  }
}
