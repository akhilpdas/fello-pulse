export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Query = Record<string, string | number | number[] | undefined>;

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

/**
 * The API client. Identity is the session cookie and nothing else: no tenant or user id is ever sent
 * (002 / FR-002). State-changing requests carry `X-Requested-With`, which the server requires of
 * cookie-authenticated writes (CSRF). `onUnauthorized` tells the app the session is gone.
 */
export function createClient(fetchImpl: typeof fetch = fetch, onUnauthorized?: () => void) {
  async function request<T>(method: string, path: string, query?: Query, body?: unknown): Promise<T> {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query ?? {})) {
      if (v === undefined) continue;
      if (Array.isArray(v)) v.forEach((x) => qs.append(k, String(x)));
      else qs.set(k, String(v));
    }
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (!SAFE.has(method)) headers["X-Requested-With"] = "pulse";
    const url = `/api${path}${qs.size ? "?" + qs : ""}`;
    const res = await fetchImpl(url, {
      method, headers, credentials: "include", body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await res.json().catch(() => null);
    if (res.status === 401) onUnauthorized?.();
    if (!res.ok) throw new ApiError(res.status, typeof data?.detail === "string" ? data.detail : res.statusText);
    return data as T;
  }

  return {
    get: <T>(path: string, query?: Query) => request<T>("GET", path, query),
    post: <T>(path: string, body: unknown) => request<T>("POST", path, undefined, body),
    patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, undefined, body),
    del: <T>(path: string) => request<T>("DELETE", path),
  };
}
export type Client = ReturnType<typeof createClient>;
