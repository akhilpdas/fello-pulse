import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { createClient, type Client, type Session } from "../api/client";

const KEY = "pulse.session";
function load(): Session {
  try { return JSON.parse(localStorage.getItem(KEY) ?? "") as Session; } catch { return { tenantId: "" }; }
}

interface Ctx { session: Session; setSession: (s: Session) => void; api: Client }
const SessionCtx = createContext<Ctx | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, set] = useState<Session>(load);
  const value = useMemo<Ctx>(() => ({
    session, api: createClient(session),
    setSession: (s) => { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* storage unavailable */ } set(s); },
  }), [session]);
  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>;
}
export function useSession(): Ctx {
  const c = useContext(SessionCtx);
  if (!c) throw new Error("SessionProvider missing");
  return c;
}
