const INTERNAL_HEADER = "x-zkast-internal-token";

export type PipelineFetchInit = RequestInit & {
  /** When false, skip throwing on non-OK responses (caller inspects `res.ok`). */
  throwOnError?: boolean;
};

/**
 * Server-only HTTP client for the internal pipeline contract (specs/apis.md).
 */
export async function pipelineFetch(
  path: string,
  init: PipelineFetchInit = {},
): Promise<Response> {
  const { throwOnError = true, ...rest } = init;
  const base = (process.env.PIPELINE_INTERNAL_URL ?? "http://localhost:8000").replace(
    /\/$/,
    "",
  );
  const token = process.env.INTERNAL_PIPELINE_TOKEN;
  if (!token) {
    throw new Error("INTERNAL_PIPELINE_TOKEN is not configured");
  }

  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(rest.headers);
  headers.set(INTERNAL_HEADER, token);

  const res = await fetch(url, {
    ...rest,
    headers,
    cache: "no-store",
  });

  if (!res.ok && throwOnError) {
    const body = await res.text().catch(() => "");
    throw new Error(
      `Pipeline request failed ${res.status} ${res.statusText}${body ? `: ${body.slice(0, 200)}` : ""}`,
    );
  }

  return res;
}
