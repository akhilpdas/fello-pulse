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
  it("sends no identity headers, includes the session cookie, and marks only state-changing requests", async () => {
    const { f, calls } = fakeFetch(200, { rows: [] });
    const api = createClient(f);
    await api.get("/queue");
    await api.post("/actions/1/approve", {});
    expect(calls[0].url).toBe("/api/queue");
    for (const c of calls) {
      const h = c.init.headers as Record<string, string>;
      expect(c.init.credentials).toBe("include");
      expect(h["X-Tenant-Id"]).toBeUndefined();
      expect(h["X-User-Id"]).toBeUndefined();
    }
    expect((calls[0].init.headers as Record<string, string>)["X-Requested-With"]).toBeUndefined();
    expect((calls[1].init.headers as Record<string, string>)["X-Requested-With"]).toBe("pulse");
  });

  it("tells the app when the session is gone, and still rejects", async () => {
    const { f } = fakeFetch(401, { detail: "not authenticated" });
    let called = 0;
    const api = createClient(f, () => { called += 1; });
    await expect(api.get("/queue")).rejects.toMatchObject({ status: 401 });
    expect(called).toBe(1);
  });

  it("encodes query params and skips undefined ones", async () => {
    const { f, calls } = fakeFetch(200, {});
    await createClient(f).get("/actions", { state: "drafted", x: undefined });
    expect(calls[0].url).toBe("/api/actions?state=drafted");
  });

  it("repeats the key for array params, as FastAPI list queries expect", async () => {
    const { f, calls } = fakeFetch(200, {});
    await createClient(f).get("/accounts/a/evidence", { event_ids: [3, 4] });
    expect(calls[0].url).toBe("/api/accounts/a/evidence?event_ids=3&event_ids=4");
  });

  it("surfaces the server's error detail instead of swallowing it", async () => {
    const { f } = fakeFetch(409, { detail: "decision already made" });
    const api = createClient(f);
    await expect(api.post("/actions/1/approve", {})).rejects.toMatchObject({
      status: 409, message: "decision already made",
    });
    await expect(api.post("/actions/1/approve", {})).rejects.toBeInstanceOf(ApiError);
  });
});
