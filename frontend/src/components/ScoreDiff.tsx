import { useState } from "react";
import { useSession } from "../lib/session";
import type { ScoreDiff as Diff } from "../api/types";
import { formatDelta, formatPercent } from "../lib/format";

export function ScoreDiffView({ accountId, currentAsOf }: { accountId: string; currentAsOf: string }) {
  const { api } = useSession();
  const [from, setFrom] = useState("");
  const [diff, setDiff] = useState<Diff | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function compare() {
    setError(null); setDiff(null);
    try {
      setDiff(await api.get<Diff>(`/accounts/${accountId}/score-diff`, {
        from_as_of: new Date(from).toISOString(), to_as_of: currentAsOf,
      }));
    } catch (e) { setError((e as Error).message); }
  }

  return (
    <div>
      <label>Compare against the score as of{" "}
        <input type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} />
      </label>{" "}
      <button onClick={compare} disabled={!from}>Compare</button>
      {error && <p className="error" role="alert">{error}</p>}
      {diff && (
        <>
          <p>
            {formatPercent(diff.from.probability)} → {formatPercent(diff.to.probability)}{" "}
            ({formatDelta(diff.probability_delta)})
          </p>
          <table>
            <thead><tr><th>Feature</th><th>From</th><th>To</th><th>Contribution change</th></tr></thead>
            <tbody>
              {diff.feature_diffs.slice(0, 10).map((d) => (
                <tr key={d.feature}>
                  <td>{d.feature}</td><td>{d.from_value ?? "—"}</td><td>{d.to_value ?? "—"}</td>
                  <td>{d.contribution_delta >= 0 ? "+" : ""}{d.contribution_delta.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
