import { Link } from "react-router-dom";
import { Status } from "../components/Status";
import { TierBadge } from "../components/TierBadge";
import type { Queue as QueueT } from "../api/types";
import { driverLabel, formatDelta, formatMoney, formatPercent, renewalLabel } from "../lib/format";
import { useApi } from "../lib/useApi";

export function QueuePage() {
  const { data, error, loading } = useApi((api) => api.get<QueueT>("/queue"));
  return (
    <section>
      <h1>This week's queue</h1>
      <Status loading={loading} error={error} empty={data && !data.rows.length && "Nothing scored yet — run a cycle."} />
      {data && data.rows.length > 0 && (
        <>
          <p className="muted">As of {new Date(data.as_of!).toLocaleDateString()}</p>
          <table>
            <thead><tr><th>#</th><th>Account</th><th>Tier</th><th>Risk</th><th>Value at risk</th><th>Renewal</th><th>Why</th><th>Since last cycle</th></tr></thead>
            <tbody>
              {data.rows.map((r, i) => (
                <tr key={r.account_id}>
                  <td>{i + 1}</td>
                  <td><Link to={`/accounts/${r.account_id}`}>{r.account_name}</Link></td>
                  <td><TierBadge tier={r.tier} /></td>
                  <td>{formatPercent(r.probability)}</td>
                  <td>{formatMoney(r.value_at_risk_cents)}</td>
                  <td>{renewalLabel(r.days_to_renewal)}</td>
                  <td>{driverLabel(r.dominant_driver)}</td>
                  <td>{formatDelta(r.delta)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">{data.below_cut} more account{data.below_cut === 1 ? "" : "s"} below the weekly capacity cut.</p>
        </>
      )}
    </section>
  );
}
