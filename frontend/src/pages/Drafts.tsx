import { useState } from "react";
import { Link } from "react-router-dom";
import { Status } from "../components/Status";
import type { Action } from "../api/types";
import { canApprove, describeState } from "../lib/actionState";
import { driverLabel } from "../lib/format";
import { useSession } from "../lib/session";
import { useApi } from "../lib/useApi";

function Draft({ a, onChanged }: { a: Action; onChanged: (what: string, result: Action) => void }) {
  const { api } = useSession();
  const [body, setBody] = useState(a.body);
  const [subject, setSubject] = useState(a.subject ?? "");
  const [err, setErr] = useState<string | null>(null);
  const editable = a.state === "drafted";
  const meaning = describeState(a);

  async function run(what: string, fn: () => Promise<Action>) {
    setErr(null);
    try { onChanged(what, await fn()); } catch (e) { setErr((e as Error).message); }
  }
  return (
    <article className="draft">
      <header><strong>{a.play_key}</strong> <span className={`state state-${a.state}`}>{a.state}</span>
        <p className={`state-note tone-${meaning.tone}`} role="status">{meaning.text}</p>
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
      {(editable || canApprove(a.state)) && (
        <footer>
          {editable && <button onClick={() => run("Saved", () => api.patch<Action>(`/actions/${a.id}`, { subject, body }))}>Save edit</button>}{" "}
          <button onClick={() => run("Approve & send", () => api.post<Action>(`/actions/${a.id}/approve`, {}))}>Approve & send</button>{" "}
          {editable && <button onClick={() => run("Reject", () => api.post<Action>(`/actions/${a.id}/reject`, {}))}>Reject</button>}
        </footer>
      )}
      {err && <p className="error" role="alert">{err}</p>}
    </article>
  );
}

export function DraftsPage() {
  const [state, setState] = useState("drafted");
  const { data, error, loading, reload } = useApi((api) => api.get<{ rows: Action[] }>("/actions", { state }), [state]);
  // What just happened to the draft you acted on. Without it an approved draft simply leaves this list -- and when it was
  // blocked (outbound off, no contact, opted out) nothing would say it had not been sent.
  const [notice, setNotice] = useState<{ what: string; a: Action } | null>(null);
  const noticeText = notice && describeState(notice.a);
  return (
    <section>
      <h1>Draft review</h1>
      {notice && noticeText && (
        <p className={`state-note draft-notice tone-${noticeText.tone}`} role="status">
          <strong>{notice.what}:</strong> {noticeText.text} <button className="link" onClick={() => setNotice(null)}>Dismiss</button>
        </p>
      )}
      <label>Show{" "}
        <select value={state} onChange={(e) => setState(e.target.value)}>
          {["drafted", "sent", "send_unconfirmed", "send_failed", "outbound_disabled", "not_configured", "no_recipient", "opted_out", "rejected"].map((s) => <option key={s}>{s}</option>)}
        </select>
      </label>
      <Status loading={loading} error={error} empty={data && !data.rows.length && `No ${state} actions.`} />
      {data?.rows.map((a) => <Draft key={a.id + a.state} a={a} onChanged={(what, result) => { setNotice({ what, a: result }); reload(); }} />)}
    </section>
  );
}
