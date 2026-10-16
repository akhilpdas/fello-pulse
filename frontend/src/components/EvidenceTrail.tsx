import { useState } from "react";
import { useSession } from "../lib/session";
import type { SourceEvent } from "../api/types";
import { driverLabel } from "../lib/format";

// Evidence is resolved lazily, per driver, down to the original source payload.
export function EvidenceTrail({ accountId, evidence }: { accountId: string; evidence: Record<string, number[]> }) {
  const { api } = useSession();
  const [open, setOpen] = useState<Record<string, SourceEvent[] | "loading" | string>>({});

  async function toggle(driver: string, ids: number[]) {
    if (open[driver]) { const { [driver]: _, ...rest } = open; setOpen(rest); return; }
    setOpen({ ...open, [driver]: "loading" });
    try {
      const r = await api.get<{ events: SourceEvent[] }>(`/accounts/${accountId}/evidence`, { event_ids: ids.slice(0, 20) });
      setOpen((o) => ({ ...o, [driver]: r.events }));
    } catch (e) { setOpen((o) => ({ ...o, [driver]: (e as Error).message })); }
  }

  const drivers = Object.entries(evidence).filter(([, ids]) => ids.length);
  if (!drivers.length) return <p className="muted">No source records back this score.</p>;
  return (
    <div>
      {drivers.map(([driver, ids]) => {
        const state = open[driver];
        return (
          <div key={driver} className="evidence-group">
            <button className="link" onClick={() => toggle(driver, ids)}>
              {state ? "▾" : "▸"} {driverLabel(driver)} — {ids.length} source record{ids.length === 1 ? "" : "s"}
            </button>
            {state === "loading" && <p className="muted">Loading…</p>}
            {typeof state === "string" && state !== "loading" && <p className="error">{state}</p>}
            {Array.isArray(state) && state.map((e) => (
              <details key={e.id} className="event">
                <summary>{e.source} · {e.event_type} · {new Date(e.occurred_at).toLocaleDateString()}</summary>
                <pre>{JSON.stringify(e.payload, null, 2)}</pre>
              </details>
            ))}
          </div>
        );
      })}
    </div>
  );
}
