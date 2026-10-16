import { describe, expect, it } from "vitest";
import { fetchMe, login, logout } from "./auth";
import { createClient } from "./client";

function fakeFetch(status: number, body: unknown) {
  const calls: { url: string; init: RequestInit }[] = [];
  const f = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  }) as unknown as typeof fetch;
  return { f, calls };
}

const WHO = {
  user: { id: "u1", name: "Ana", role: "operator", email: "ana@northwind.test" },
  tenant: { id: "t1", slug: "northwind" },
};

describe("auth api (002 / FR-011)", () => {
  it("signs in with workspace, email and password — and never sends ids", async () => {
    const { f, calls } = fakeFetch(200, WHO);
    const who = await login(createClient(f), "northwind", "ana@northwind.test", "a long passphrase");
    expect(calls[0].url).toBe("/api/auth/login");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({
      workspace: "northwind", email: "ana@northwind.test", password: "a long passphrase",
    });
    expect(who.user.role).toBe("operator");
  });

  it("surfaces a failed sign-in as an error the form can show", async () => {
    const { f } = fakeFetch(401, { detail: "invalid credentials" });
    await expect(login(createClient(f), "w", "e", "p")).rejects.toMatchObject({ status: 401, message: "invalid credentials" });
  });

  it("asks the server who the cookie belongs to, and treats 401 as signed out (null)", async () => {
    expect(await fetchMe(createClient(fakeFetch(200, WHO).f))).toEqual(WHO);
    expect(await fetchMe(createClient(fakeFetch(401, { detail: "not authenticated" }).f))).toBeNull();
  });

  it("signs out with a POST", async () => {
    const { f, calls } = fakeFetch(200, { ok: true });
    await logout(createClient(f));
    expect(calls[0].init.method).toBe("POST");
    expect(calls[0].url).toBe("/api/auth/logout");
  });
});
