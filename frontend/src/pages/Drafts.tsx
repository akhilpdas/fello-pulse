import { useState } from "react";
import { Link } from "react-router-dom";
import { Status } from "../components/Status";
import type { Action } from "../api/types";
import { driverLabel } from "../lib/format";
import { useSession } from "../lib/session";
import { useApi } from "../lib/useApi";

function Draft({ a, onChanged }: { a: Action; onChanged: () => void }) {
  const { api } = useSession();
  const [body, setBody] = useState(a.body);
  const [subject, setSubject] = useState(a.subject ?? "");
  const [err, setErr] = useState<string | null>(null);
  const editable = a.state === "drafted";

  async function run(fn: () => Promise<unknown>) {
    setErr(null);
    try { await fn(); onChanged(); } catch (e) { setErr((e as Error).message); }
  }
  return (
    <article className="draft">
      <header><strong>{a.play_key}</strong> <span className={`state state-${a.state}`}>{a.state}</span>
        {a.state_reason && <span className="muted"> — {a.state_reason}</span>}
        {" "}<Link to={`/accounts/${a.account_id}`}>account</Link></header>
      <div className="draft-grid">
        <div>
          <input value={subject} disabled={!editable} onChange={(e) => setSubject(e.target.value)} aria-label="Subject" />
          <textarea value={body} disabled={!editable} rows={8} onChange={(e) => setBody(e.target.value)} aria-label="Body" />
        </div>
        <aside>
          <h4>Grounded in</h4>
          {a.grounding?.evidence_drivers?.length
            ? <ul>{a.grounding.evidence_drivers.map((d) => <li key={d}>{driverLabel(d)}</li>)}</ul>
            : <p className="muted">No grounding recorded.</p>}
          <p className="muted">Drafted by {a.draft_source}. <Link to={`/accounts/${a.account_id}`}>See the evidence</Link></p>
        </aside>
      </div>
      {editable && (
        <footer>
          <button onClick={() => run(() => api.patch(`/actions/${a.id}`, { subject, body }))}>Save edit</button>{" "}
          <button onClick={() => run(() => api.post(`/actions/${a.id}/approve`, {}))}>Approve & send</button>{" "}
          <button onClick={() => run(() => api.post(`/actions/${a.id}/reject`, {}))}>Reject</button>
        </footer>
      )}
      {err && <p className="error" role="alert">{err}</p>}
    </article>
  );
}

export function DraftsPage() {
  const [state, setState] = useState("drafted");
  const { data, error, loading, reload } = useApi((api) => api.get<{ rows: Action[] }>("/actions", { state }), [state]);
  return (
    <section>
      <h1>Draft review</h1>
      <label>Show{" "}
        <select value={state} onChange={(e) => setState(e.target.value)}>
          {["drafted", "sent", "send_failed", "rejected"].map((s) => <option key={s}>{s}</option>)}
        </select>
      </label>
      <Status loading={loading} error={error} empty={data && !data.rows.length && `No ${state} actions.`} />
      {data?.rows.map((a) => <Draft key={a.id + a.state} a={a} onChanged={reload} />)}
    </section>
  );
}
