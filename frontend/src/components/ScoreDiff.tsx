import { useState } from "react";
import { useSession } from "../lib/session";
import type { ScoreDiff as Diff, Snapshots } from "../api/types";
import { snapshotLabel } from "../lib/browse";
import { formatDelta, formatPercent } from "../lib/format";
import { useApi } from "../lib/useApi";

export function ScoreDiffView({ accountId, currentAsOf }: { accountId: string; currentAsOf: string }) {
  const { api } = useSession();
  const [from, setFrom] = useState("");
  const [diff, setDiff] = useState<Diff | null>(null);
  // Only weeks that exist can be compared, and the server matches the stored timestamp exactly -- so offer those, untouched.
  const { data: weeks } = useApi((a) => a.get<Snapshots>("/queue/snapshots"));
  const earlier = (weeks?.snapshots ?? []).filter((w) => new Date(w.as_of).getTime() !== new Date(currentAsOf).getTime());
  const [error, setError] = useState<string | null>(null);

  async function compare() {
    setError(null); setDiff(null);
    try {
      setDiff(await api.get<Diff>(`/accounts/${accountId}/score-diff`, {
        from_as_of: from, to_as_of: currentAsOf,
      }));
    } catch (e) { setError((e as Error).message); }
  }

  return (
    <div>
      <label>Compare against the score as of{" "}
        <select value={from} onChange={(e) => setFrom(e.target.value)}>
          <option value="">{earlier.length ? "Choose a week…" : "No earlier weeks scored yet"}</option>
          {earlier.map((w) => <option key={w.as_of} value={w.as_of}>{snapshotLabel(w, false)}</option>)}
        </select>
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
