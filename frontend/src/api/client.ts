export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface Session {
  tenantId: string;
  userId?: string;
}

type Query = Record<string, string | number | number[] | undefined>;

export function createClient(session: Session, fetchImpl: typeof fetch = fetch) {
  const headers: Record<string, string> = { "X-Tenant-Id": session.tenantId, "Content-Type": "application/json" };
  if (session.userId) headers["X-User-Id"] = session.userId;

  async function request<T>(method: string, path: string, query?: Query, body?: unknown): Promise<T> {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query ?? {})) {
      if (v === undefined) continue;
      if (Array.isArray(v)) v.forEach((x) => qs.append(k, String(x)));
      else qs.set(k, String(v));
    }
    const url = `/api${path}${qs.size ? "?" + qs : ""}`;
    const res = await fetchImpl(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(res.status, typeof data?.detail === "string" ? data.detail : res.statusText);
    return data as T;
  }

  return {
    get: <T>(path: string, query?: Query) => request<T>("GET", path, query),
    post: <T>(path: string, body: unknown) => request<T>("POST", path, undefined, body),
    patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, undefined, body),
  };
}
export type Client = ReturnType<typeof createClient>;
