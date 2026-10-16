import { useParams } from "react-router-dom";
import { DriverBars } from "../components/DriverBar";
import { EvidenceTrail } from "../components/EvidenceTrail";
import { ScoreDiffView } from "../components/ScoreDiff";
import { Status } from "../components/Status";
import { TierBadge } from "../components/TierBadge";
import type { AccountDetail } from "../api/types";
import { driverLabel, formatMoney, formatPercent } from "../lib/format";
import { useApi } from "../lib/useApi";

export function AccountPage() {
  const { id } = useParams();
  const { data: a, error, loading } = useApi((api) => api.get<AccountDetail>(`/accounts/${id}`), [id]);
  if (!a) return <Status loading={loading} error={error} />;
  const features = Object.entries(a.feature_values).sort(([x], [y]) => x.localeCompare(y));
  return (
    <section>
      <h1>{a.account_name} <TierBadge tier={a.tier} /></h1>
      {a.tier === "abstain" ? (
        <p className="warn">Not scored: <code>{a.abstain_reason}</code>. This is missing evidence, not a clean bill of health.</p>
      ) : (
        <p>{formatPercent(a.probability)} risk · {formatMoney(a.value_at_risk_cents)} at risk · mainly {driverLabel(a.dominant_driver)}</p>
      )}
      <h2>What is driving it</h2>
      <DriverBars totals={a.driver_totals} />
      <h2>Evidence</h2>
      <EvidenceTrail accountId={a.account_id} evidence={a.evidence} />
      <h2>What moved</h2>
      <ScoreDiffView accountId={a.account_id} currentAsOf={a.as_of} />
      <h2>Feature values</h2>
      <details><summary>{features.length} features ({a.days_of_history} days of history)</summary>
        <table><tbody>
          {features.map(([k, v]) => <tr key={k}><td>{k}</td><td>{v === null ? <span className="muted">absent</span> : v}</td></tr>)}
        </tbody></table>
      </details>
    </section>
  );
}
