import { describe, expect, it } from "vitest";
import { canApprove, describeState } from "./actionState";

describe("what a draft's state means to a CSM (002 / FR-013, FR-018)", () => {
  it("says an unconfirmed send must be checked, never simply retried", () => {
    const d = describeState({ state: "send_unconfirmed", state_reason: "TimeoutError", redirected_to: null });
    expect(d.tone).toBe("warn");
    expect(d.text.toLowerCase()).toContain("check");
    expect(d.text.toLowerCase()).not.toContain("try again");
  });

  it.each([
    ["outbound_disabled", "switched off"],
    ["not_configured", "not set up"],
    ["no_recipient", "no known contact"],
    ["opted_out", "asked not to be emailed"],
  ])("explains %s in plain words", (state, phrase) => {
    expect(describeState({ state, state_reason: null, redirected_to: null }).text.toLowerCase()).toContain(phrase);
  });

  it("makes a demo redirect and a demo capture visible, so nobody thinks a customer was emailed", () => {
    expect(describeState({ state: "sent", state_reason: null, redirected_to: "demo@pulse.example.com" }).text)
      .toContain("demo@pulse.example.com");
    const captured = describeState({ state: "sent", state_reason: "demo mode: captured", redirected_to: "captured (no test inbox configured)" });
    expect(captured.text.toLowerCase()).toContain("not delivered");
  });

  it("a plain send is just 'sent'", () => {
    expect(describeState({ state: "sent", state_reason: null, redirected_to: null }).text).toBe("Sent to the customer.");
  });

  it("only states where the message definitely did not leave can be approved again", () => {
    for (const s of ["drafted", "outbound_disabled", "not_configured", "no_recipient", "opted_out", "send_failed"]) {
      expect(canApprove(s)).toBe(true);
    }
    for (const s of ["sent", "send_unconfirmed", "rejected", "approved"]) expect(canApprove(s)).toBe(false);
  });
});
