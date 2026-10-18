import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Status } from "../components/Status";
import { TierBadge } from "../components/TierBadge";
import { WeekPicker } from "../components/WeekPicker";
import type { BrowseResult } from "../api/types";
import { browseQuery, pageWindow } from "../lib/browse";
import { driverLabel, formatDelta, formatMoney, formatPercent, renewalLabel } from "../lib/format";
import { useApi } from "../lib/useApi";

const PAGE_SIZE = 50;
const TIERS = ["red", "amber", "green"];
const DRIVERS = ["usage_decline", "support_experience", "relationship_engagement", "payment_friction", "commercial_signals", "data_quality"];

/** Every scored account in ranked order — the part of the ranking `/` cuts off at the weekly capacity. */
export function BrowsePage() {
  const [params, setParams] = useSearchParams();
  const asOf = params.get("as_of") ?? "";
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [tier, setTier] = useState("");
  const [driver, setDriver] = useState("");
  const [page, setPage] = useState(0);

  useEffect(() => { // wait for a pause in typing, and go back to the first page whenever the question changes
    const t = setTimeout(() => { setQ(search); setPage(0); }, 250);
    return () => clearTimeout(t);
  }, [search]);

  const { data, error, loading } = useApi(
    (api) => api.get<BrowseResult>("/queue/all", browseQuery({ q, tier, driver, asOf, page, pageSize: PAGE_SIZE })),
    [q, tier, driver, asOf, page],
  );
  const w = data ? pageWindow(data.total, data.offset, data.limit) : null;

  return (
    <section>
      <h1>All accounts</h1>
      <p className="muted"><Link to={asOf ? `/?as_of=${encodeURIComponent(asOf)}` : "/"}>← This week's queue</Link>
        {" "}· ranked by priority; the first {data?.capacity ?? "…"} are the weekly queue.</p>
      <div className="filters">
        <WeekPicker value={asOf} onChange={(v) => { setPage(0); setParams(v ? { as_of: v } : {}); }} />
        <label className="filter">Search accounts
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="name contains…" />
        </label>
        <label className="filter">Tier
          <select value={tier} onChange={(e) => { setTier(e.target.value); setPage(0); }}>
            <option value="">All tiers</option>
            {TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="filter">Driver
          <select value={driver} onChange={(e) => { setDriver(e.target.value); setPage(0); }}>
            <option value="">All drivers</option>
            {DRIVERS.map((d) => <option key={d} value={d}>{driverLabel(d)}</option>)}
          </select>
        </label>
      </div>
      <Status loading={loading && !data} error={error} empty={data && !data.rows.length && "No accounts match."} />
      {data && w && data.rows.length > 0 && (
        <>
          <table>
            <thead><tr><th>#</th><th>Account</th><th>Tier</th><th>Risk</th><th>Value at risk</th><th>Renewal</th><th>Why</th><th>Since last cycle</th></tr></thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.account_id} className={r.in_queue ? "in-queue" : undefined}>
                  <td>{r.rank}</td>
                  <td><Link to={`/accounts/${r.account_id}`}>{r.account_name}</Link> <span className="muted ref">{r.external_ref}</span></td>
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
          <div className="pager">
            <button disabled={!w.hasPrev} onClick={() => setPage(page - 1)}>Previous</button>
            <span>Showing {w.from}–{w.to} of {data.total.toLocaleString("en-US")}</span>
            <button disabled={!w.hasNext} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </>
      )}
    </section>
  );
}
