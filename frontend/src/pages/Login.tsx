import { useState, type FormEvent } from "react";
import { useSession } from "../lib/session";

export function LoginPage() {
  const { signIn } = useSession();
  const [workspace, setWorkspace] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null); setBusy(true);
    try { await signIn(workspace.trim(), email.trim(), password); }
    catch (ex) { setErr((ex as Error).message); }
    finally { setBusy(false); }
  }
  return (
    <form className="login" onSubmit={submit}>
      <h1>Sign in to Pulse</h1>
      <label>Workspace <input value={workspace} onChange={(e) => setWorkspace(e.target.value)} autoComplete="organization" required placeholder="northwind" /></label>
      <label>Email <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required /></label>
      <label>Password <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
      <button disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      {err && <p className="error" role="alert">{err}</p>}
    </form>
  );
}
