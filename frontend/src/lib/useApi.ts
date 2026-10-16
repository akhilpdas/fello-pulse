import { useCallback, useEffect, useState } from "react";
import { useSession } from "./session";
import type { Client } from "../api/client";

export function useApi<T>(load: (api: Client) => Promise<T>, deps: unknown[] = []) {
  const { api, session } = useSession();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    if (!session.tenantId) { setLoading(false); return; }
    setLoading(true);
    load(api).then((d) => { setData(d); setError(null); })
      .catch((e: Error) => setError(e.message)).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, ...deps]);
  useEffect(reload, [reload]);
  return { data, error, loading, reload };
}
