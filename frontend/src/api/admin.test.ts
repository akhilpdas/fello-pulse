import { describe, expect, it } from "vitest";
import { addOptOut, createUser, getAudit, getOutbound, listOptOuts, listUsers, patchOutbound, patchUser, removeOptOut } from "./admin";
import { createClient } from "./client";

function fakeFetch(body: unknown = {}) {
  const calls: { url: string; init: RequestInit }[] = [];
  const f = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as unknown as typeof fetch;
  return { api: createClient(f), calls };
}
const body = (c: { init: RequestInit }) => JSON.parse(c.init.body as string);

describe("operator api (002 / FR-004, FR-009, FR-014, FR-016)", () => {
  it("reads and changes the outbound settings", async () => {
    const { api, calls } = fakeFetch();
    await getOutbound(api);
    await patchOutbound(api, { sender_address: "csm@northwind.example.com", sender_verified: true, outbound_enabled: true });
    expect(calls[0].url).toBe("/api/admin/outbound");
    expect(calls[1].init.method).toBe("PATCH");
    expect(body(calls[1])).toEqual({ sender_address: "csm@northwind.example.com", sender_verified: true, outbound_enabled: true });
  });

  it("manages the opt-out list", async () => {
    const { api, calls } = fakeFetch();
    await listOptOuts(api);
    await addOptOut(api, "gone@acme.example.com", "replied stop");
    await removeOptOut(api, "abc");
    expect(calls.map((c) => [c.init.method, c.url])).toEqual([
      ["GET", "/api/admin/opt-outs"], ["POST", "/api/admin/opt-outs"], ["DELETE", "/api/admin/opt-outs/abc"]]);
    expect(body(calls[1])).toEqual({ email: "gone@acme.example.com", reason: "replied stop" });
  });

  it("manages users and reads the audit trail", async () => {
    const { api, calls } = fakeFetch();
    await listUsers(api);
    await createUser(api, { email: "n@x.test", name: "N", role: "csm", password: "a long passphrase" });
    await patchUser(api, "u1", { disabled: true });
    await getAudit(api);
    expect(calls.map((c) => [c.init.method, c.url])).toEqual([
      ["GET", "/api/admin/users"], ["POST", "/api/admin/users"], ["PATCH", "/api/admin/users/u1"], ["GET", "/api/admin/audit"]]);
    expect(body(calls[2])).toEqual({ disabled: true });
  });
});
