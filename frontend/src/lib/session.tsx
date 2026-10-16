import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { fetchMe, login as apiLogin, logout as apiLogout, type Who } from "../api/auth";
import { createClient, type Client } from "../api/client";

type Status = "loading" | "anonymous" | "signed-in";
interface Ctx {
  status: Status;
  who: Who | null;
  api: Client;
  signIn: (workspace: string, email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}
const SessionCtx = createContext<Ctx | null>(null);

/** The session lives in an HttpOnly cookie the page cannot read; the app only ever asks the server who it is. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [who, setWho] = useState<Who | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const gone = useCallback(() => { setWho(null); setStatus("anonymous"); }, []);
  const api = useMemo(() => createClient(fetch, gone), [gone]);

  useEffect(() => {
    fetchMe(api).then((w) => { setWho(w); setStatus(w ? "signed-in" : "anonymous"); }).catch(gone);
  }, [api, gone]);

  const value = useMemo<Ctx>(() => ({
    status, who, api,
    signIn: async (workspace, email, password) => {
      const w = await apiLogin(api, workspace, email, password);
      setWho(w); setStatus("signed-in");
    },
    signOut: async () => { try { await apiLogout(api); } finally { gone(); } },
  }), [status, who, api, gone]);
  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>;
}
export function useSession(): Ctx {
  const c = useContext(SessionCtx);
  if (!c) throw new Error("SessionProvider missing");
  return c;
}
