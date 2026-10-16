import { useState } from "react";
import { liftSuppression, postFeedback, suppressAccount } from "../api/accountActions";
import { useSession } from "../lib/session";

/** What a CSM can say back to the system about this account (001/FR-047, FR-048). */
export function AccountActions({ accountId }: { accountId: string }) {
  const { api } = useSession();
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [days, setDays] = useState(14);
  const [msg, setMsg] = useState<string | null>(null);

  const run = async (done: string, fn: () => Promise<unknown>) => {
    try { await fn(); setMsg(done); } catch (e) { setMsg((e as Error).message); }
  };

  return (
    <section>
      <h2>Your judgement</h2>
      <p className="muted">Retained as a label for the model, not just hidden.</p>
      <input placeholder="note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
      <button onClick={() => run("Marked as a false positive.", () => postFeedback(api, accountId, "false_positive", note || undefined))}>
        Mark false positive
      </button>{" "}
      <button onClick={() => run("Recorded as a true positive.", () => postFeedback(api, accountId, "true_positive", note || undefined))}>
        Confirm risk is real
      </button>
      <div>
        <input placeholder="why suppress? (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 14, 30, 90].map((d) => <option key={d} value={d}>{d} days</option>)}
        </select>
        <button disabled={!reason.trim()} onClick={() => run(`Suppressed from the queue for ${days} days; still scored.`, () => suppressAccount(api, accountId, reason, days))}>
          Suppress from queue
        </button>{" "}
        <button onClick={() => run("Suppression lifted.", () => liftSuppression(api, accountId))}>Lift suppression</button>
      </div>
      {msg && <p role="status">{msg}</p>}
    </section>
  );
}
