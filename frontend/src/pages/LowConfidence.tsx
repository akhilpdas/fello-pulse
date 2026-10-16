import { Link } from "react-router-dom";
import { Status } from "../components/Status";
import type { LowConfidenceRow } from "../api/types";
import { formatMoney } from "../lib/format";
import { useApi } from "../lib/useApi";

export function LowConfidencePage() {
  const { data, error, loading } = useApi((api) => api.get<{ rows: LowConfidenceRow[] }>("/queue/low-confidence"));
  return (
    <section>
      <h1>Low confidence</h1>
      <p className="muted">Accounts the system declined to score. They are never shown as healthy; each needs a data fix or a manual look.</p>
      <Status loading={loading} error={error} empty={data && !data.rows.length && "No accounts are in the low-confidence bucket."} />
      {data && data.rows.length > 0 && (
        <table>
          <thead><tr><th>Account</th><th>Reason</th><th>Value</th><th>What to do</th></tr></thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.account_id}>
                <td><Link to={`/accounts/${r.account_id}`}>{r.account_name}</Link></td>
                <td><code>{r.abstain_reason}</code></td>
                <td>{formatMoney(r.value_at_risk_cents)}</td>
                <td>{r.remedy}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
