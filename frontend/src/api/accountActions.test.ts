import { describe, expect, it } from "vitest";
import { liftSuppression, postFeedback, suppressAccount } from "./accountActions";
import { createClient } from "./client";

function fakeFetch(status: number, body: unknown) {
  const calls: { url: string; init: RequestInit }[] = [];
  const f = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as unknown as typeof fetch;
  return { f, calls };
}

describe("account actions (001/FR-047, FR-048)", () => {
  it("posts feedback with the kind and note", async () => {
    const { f, calls } = fakeFetch(201, { id: "x" });
    await postFeedback(createClient(f), "a-1", "false_positive", "renewed early");
    expect(calls[0].url).toBe("/api/accounts/a-1/feedback");
    expect(calls[0].init.method).toBe("POST");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ kind: "false_positive", note: "renewed early" });
  });

  it("suppresses for N days from the given instant, with the reason", async () => {
    const { f, calls } = fakeFetch(201, {});
    const now = new Date("2026-10-16T09:00:00Z");
    await suppressAccount(createClient(f), "a-1", "letting this one go", 14, now);
    expect(calls[0].url).toBe("/api/accounts/a-1/suppress");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({
      reason: "letting this one go", expires_at: "2026-10-30T09:00:00.000Z",
    });
  });

  it("lifts a suppression with DELETE", async () => {
    const { f, calls } = fakeFetch(200, { lifted: 1 });
    await liftSuppression(createClient(f), "a-1");
    expect(calls[0].init.method).toBe("DELETE");
    expect(calls[0].url).toBe("/api/accounts/a-1/suppress");
  });
});
