import { describe, expect, it } from "vitest";
import { ApiError, createClient } from "./client";

function fakeFetch(status: number, body: unknown) {
  const calls: { url: string; init: RequestInit }[] = [];
  const f = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as unknown as typeof fetch;
  return { f, calls };
}

describe("api client", () => {
  it("sends the tenant and user headers on every request, under the /api prefix", async () => {
    const { f, calls } = fakeFetch(200, { rows: [] });
    const api = createClient({ tenantId: "t-1", userId: "u-1" }, f);
    await api.get("/queue");
    expect(calls[0].url).toBe("/api/queue");
    const h = calls[0].init.headers as Record<string, string>;
    expect(h["X-Tenant-Id"]).toBe("t-1");
    expect(h["X-User-Id"]).toBe("u-1");
  });

  it("encodes query params and skips undefined ones", async () => {
    const { f, calls } = fakeFetch(200, {});
    await createClient({ tenantId: "t" }, f).get("/actions", { state: "drafted", x: undefined });
    expect(calls[0].url).toBe("/api/actions?state=drafted");
  });

  it("repeats the key for array params, as FastAPI list queries expect", async () => {
    const { f, calls } = fakeFetch(200, {});
    await createClient({ tenantId: "t" }, f).get("/accounts/a/evidence", { event_ids: [3, 4] });
    expect(calls[0].url).toBe("/api/accounts/a/evidence?event_ids=3&event_ids=4");
  });

  it("surfaces the server's error detail instead of swallowing it", async () => {
    const { f } = fakeFetch(409, { detail: "decision already made" });
    const api = createClient({ tenantId: "t" }, f);
    await expect(api.post("/actions/1/approve", {})).rejects.toMatchObject({
      status: 409, message: "decision already made",
    });
    await expect(api.post("/actions/1/approve", {})).rejects.toBeInstanceOf(ApiError);
  });
});
