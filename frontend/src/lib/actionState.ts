/** What a draft's state means, in words a CSM can act on. */
export interface StateInput { state: string; state_reason: string | null; redirected_to: string | null }
export interface StateText { text: string; tone: "ok" | "warn" | "info" | "bad" }

/** States in which the message definitely did not leave, so approving again cannot duplicate it. */
const APPROVABLE = new Set(["drafted", "outbound_disabled", "not_configured", "no_recipient", "opted_out", "send_failed"]);
export const canApprove = (state: string) => APPROVABLE.has(state);

export function describeState(a: StateInput): StateText {
  switch (a.state) {
    case "sent":
      if (a.redirected_to?.startsWith("captured"))
        return { tone: "info", text: "Demo mode: captured but not delivered — no customer was emailed." };
      if (a.redirected_to)
        return { tone: "info", text: `Demo mode: sent to the test inbox (${a.redirected_to}), not to the customer.` };
      return { tone: "ok", text: "Sent to the customer." };
    case "send_unconfirmed":
      return { tone: "warn", text: "We could not confirm delivery. Check the mail provider before doing anything — sending again could email the customer twice." };
    case "send_failed":
      return { tone: "bad", text: `The send failed${a.state_reason ? `: ${a.state_reason}` : ""}. Nothing reached the customer; you can approve again.` };
    case "outbound_disabled":
      return { tone: "warn", text: "Not sent: outbound email is switched off for this workspace. Ask an operator to switch it on." };
    case "not_configured":
      return { tone: "warn", text: `Not sent: sending is not set up${a.state_reason ? ` (${a.state_reason})` : ""}.` };
    case "no_recipient":
      return { tone: "warn", text: "Not sent: this account has no known contact. Add one in the CRM." };
    case "opted_out":
      return { tone: "warn", text: "Not sent: this contact asked not to be emailed." };
    case "drafted": return { tone: "info", text: "Waiting for your review." };
    case "rejected": return { tone: "info", text: "Rejected." };
    default: return { tone: "info", text: a.state };
  }
}
