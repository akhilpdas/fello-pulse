import { Status } from "../components/Status";
import type { Run } from "../api/types";
import { useApi } from "../lib/useApi";

export function RunsPage() {
  const { data, error, loading } = useApi((api) => api.get<Run[]>("/runs"));
  return (
    <section>
      <h1>Run log</h1>
      <p className="muted">What each autonomous cycle did — and what it chose not to do, and why.</p>
      <Status loading={loading} error={error} empty={data && !data.length && "No cycles have run yet."} />
      {data?.map((r) => (
        <article key={r.id} className="run">
          <header>
            <strong>{new Date(r.started_at).toLocaleString()}</strong>{" "}
            <span className={`state state-${r.status}`}>{r.status}</span>{" "}
            <span className="muted">{r.trigger} · {r.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(1)}s` : "running"}</span>
          </header>
          <p>{Object.entries(r.stage_counts).map(([k, v]) => `${k}: ${v}`).join(" · ") || "no stage counts"}</p>
          {r.errors.length > 0 && <p className="error">{r.errors.length} error(s): {JSON.stringify(r.errors)}</p>}
          <details>
            <summary>{r.decisions_declined.length} declined decision{r.decisions_declined.length === 1 ? "" : "s"}</summary>
            <ul>{r.decisions_declined.map((d, i) => <li key={i}><code>{d.play ?? d.stage ?? "—"}</code> {d.reason}</li>)}</ul>
          </details>
        </article>
      ))}
    </section>
  );
}
