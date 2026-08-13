/** fetch with an AbortController timeout so hung pipeline calls do not freeze the UI. */
export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init?: RequestInit & { timeoutMs?: number },
): Promise<Response> {
  const { timeoutMs = 30_000, ...rest } = init ?? {};
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...rest, signal: controller.signal });
  } finally {
    window.clearTimeout(timer);
  }
}

export function fetchTimeoutMessage(err: unknown): string {
  if (err instanceof Error && err.name === "AbortError") {
    return "Request timed out — the pipeline may be busy or unreachable.";
  }
  return err instanceof Error ? err.message : "Network error";
}

/** Parse JSON bodies; surface plain-text 5xx responses as readable errors. */
export async function readJsonResponse<T = unknown>(res: Response): Promise<T> {
  const text = await res.text();
  if (!text.trim()) {
    return {} as T;
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    const snippet = text.trim().slice(0, 120);
    throw new Error(
      res.ok
        ? "Server returned invalid JSON"
        : `Server error (${res.status}): ${snippet}`,
    );
  }
}
