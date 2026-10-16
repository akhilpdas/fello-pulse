import { useState, type FormEvent } from "react";
import { addOptOut, createUser, getAudit, getOutbound, listOptOuts, listUsers, patchOutbound, patchUser, removeOptOut,
  type AdminUser, type AuditEvent, type OptOut, type Outbound } from "../api/admin";
import { Status } from "../components/Status";
import { useApi } from "../lib/useApi";
import { useSession } from "../lib/session";

function Outbound({ onChange }: { onChange: () => void }) {
  const { api } = useSession();
  const { data, error, loading, reload } = useApi((a) => getOutbound(a));
  const [sender, setSender] = useState("");
  const [inbox, setInbox] = useState("");
  const [err, setErr] = useState<string | null>(null);
  if (!data) return <Status loading={loading} error={error} />;
  const o: Outbound = data;
  const run = async (fn: () => Promise<unknown>) => { setErr(null); try { await fn(); reload(); onChange(); } catch (e) { setErr((e as Error).message); } };
  return (
    <section>
      <h2>Outbound email</h2>
      <p className="muted">Off by default. Demo mode sends only to the test inbox (or captures, delivering nothing).{" "}
        {o.smtp_configured ? "A mail provider is configured." : "No mail provider is configured for this deployment."}</p>
      <table><tbody>
        <tr><td>Sender address</td><td>{o.sender_address ?? "—"} {o.sender_verified ? "✓ verified" : o.sender_address ? "(not verified)" : ""}</td></tr>
        <tr><td>Outbound email</td><td>{o.outbound_enabled ? "ON" : "off"}</td></tr>
        <tr><td>Demo mode</td><td>{o.demo_mode ? "ON — nothing reaches customers" : "off — real customers are emailed"}</td></tr>
        <tr><td>Test inbox</td><td>{o.test_inbox ?? "—"}</td></tr>
      </tbody></table>
      <div>
        <input aria-label="Sender address" placeholder="sender@yourcompany.com" value={sender} onChange={(e) => setSender(e.target.value)} />
        <button disabled={!sender} onClick={() => run(() => patchOutbound(api, { sender_address: sender }).then(() => setSender("")))}>Set sender</button>{" "}
        <button disabled={!o.sender_address || o.sender_verified} onClick={() => run(() => patchOutbound(api, { sender_verified: true }))}>Verify sender</button>{" "}
        <button disabled={!o.sender_verified} onClick={() => run(() => patchOutbound(api, { outbound_enabled: !o.outbound_enabled }))}>
          {o.outbound_enabled ? "Switch outbound off" : "Switch outbound on"}</button>
      </div>
      <div>
        <input aria-label="Test inbox" placeholder="demo-inbox@yourcompany.com" value={inbox} onChange={(e) => setInbox(e.target.value)} />
        <button disabled={!inbox} onClick={() => run(() => patchOutbound(api, { test_inbox: inbox }).then(() => setInbox("")))}>Set test inbox</button>{" "}
        <button onClick={() => run(() => patchOutbound(api, { demo_mode: !o.demo_mode }))}>{o.demo_mode ? "Leave demo mode" : "Back to demo mode"}</button>
      </div>
      {err && <p className="error" role="alert">{err}</p>}
    </section>
  );
}

function OptOuts({ onChange }: { onChange: () => void }) {
  const { api } = useSession();
  const { data, error, loading, reload } = useApi((a) => listOptOuts(a));
  const [email, setEmail] = useState("");
  const [err, setErr] = useState<string | null>(null);
  async function add(e: FormEvent) {
    e.preventDefault(); setErr(null);
    try { await addOptOut(api, email); setEmail(""); reload(); onChange(); } catch (x) { setErr((x as Error).message); }
  }
  return (
    <section>
      <h2>Opt-outs</h2>
      <p className="muted">Anyone here is never emailed again, by a person or by the agent.</p>
      <form onSubmit={add}><input aria-label="Opt-out email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <button>Add</button></form>
      {err && <p className="error" role="alert">{err}</p>}
      {!data ? <Status loading={loading} error={error} /> : data.length === 0 ? <p className="muted">None.</p> : (
        <ul>{data.map((o: OptOut) => (
          <li key={o.id}>{o.email} <button onClick={async () => { await removeOptOut(api, o.id); reload(); onChange(); }}>Remove</button></li>))}</ul>)}
    </section>
  );
}

function Users({ onChange }: { onChange: () => void }) {
  const { api, who } = useSession();
  const { data, error, loading, reload } = useApi((a) => listUsers(a));
  const [f, setF] = useState({ email: "", name: "", role: "csm" as "csm" | "operator", password: "" });
  const [err, setErr] = useState<string | null>(null);
  async function create(e: FormEvent) {
    e.preventDefault(); setErr(null);
    try { await createUser(api, f); setF({ ...f, email: "", name: "", password: "" }); reload(); onChange(); } catch (x) { setErr((x as Error).message); }
  }
  async function change(u: AdminUser, patch: Parameters<typeof patchUser>[2]) {
    setErr(null);
    try { await patchUser(api, u.id, patch); reload(); onChange(); } catch (x) { setErr((x as Error).message); }
  }
  return (
    <section>
      <h2>Users</h2>
      <form onSubmit={create}>
        <input aria-label="New user email" type="email" placeholder="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required />
        <input aria-label="New user name" placeholder="name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
        <select aria-label="New user role" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as "csm" | "operator" })}>
          <option value="csm">csm</option><option value="operator">operator</option></select>
        <input aria-label="New user password" type="password" placeholder="12+ characters" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required />
        <button>Create user</button>
      </form>
      {err && <p className="error" role="alert">{err}</p>}
      {!data ? <Status loading={loading} error={error} /> : (
        <table><thead><tr><th>Email</th><th>Name</th><th>Role</th><th /></tr></thead><tbody>
          {data.map((u: AdminUser) => (
            <tr key={u.id} className={u.disabled ? "muted" : ""}>
              <td>{u.email}</td><td>{u.name}</td><td>{u.role}{u.disabled ? " (disabled)" : ""}</td>
              <td>{u.id !== who?.user.id && <>
                <button onClick={() => change(u, { disabled: !u.disabled })}>{u.disabled ? "Enable" : "Disable"}</button>{" "}
                <button onClick={() => change(u, { role: u.role === "csm" ? "operator" : "csm" })}>Make {u.role === "csm" ? "operator" : "csm"}</button></>}</td>
            </tr>))}
        </tbody></table>)}
    </section>
  );
}

function Audit({ version }: { version: number }) {
  const { data, error, loading } = useApi((a) => getAudit(a), [version]); // reloads when another section changes something
  return (
    <section>
      <h2>Audit trail</h2>
      {!data ? <Status loading={loading} error={error} /> : (
        <table><thead><tr><th>When</th><th>Event</th><th>By</th><th>Subject</th></tr></thead><tbody>
          {data.slice(0, 40).map((e: AuditEvent, i) => (
            <tr key={i}><td>{new Date(e.at).toLocaleString()}</td><td>{e.event}</td><td>{e.actor_kind}</td><td>{e.subject ?? ""}</td></tr>))}
        </tbody></table>)}
    </section>
  );
}

export function AdminPage() {
  const { who } = useSession();
  const [version, setVersion] = useState(0);
  const bump = () => setVersion((v) => v + 1);
  if (who?.user.role !== "operator") return <p className="warn">This page is for operators.</p>;
  return (<><h1>Admin</h1><Outbound onChange={bump} /><OptOuts onChange={bump} /><Users onChange={bump} /><Audit version={version} /></>);
}
