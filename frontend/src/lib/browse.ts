import type { Snapshot } from "../api/types";

export interface BrowseState { q: string; tier: string; driver: string; asOf: string; page: number; pageSize: number }

/** The query string for `GET /queue/all`: only what the user set, with the page number turned into an offset. */
export function browseQuery(s: BrowseState): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  if (s.q.trim()) out.q = s.q.trim();
  if (s.tier) out.tier = s.tier;
  if (s.driver) out.driver = s.driver;
  if (s.asOf) out.as_of = s.asOf;
  out.offset = s.page * s.pageSize;
  out.limit = s.pageSize;
  return out;
}

export function pageWindow(total: number, offset: number, limit: number) {
  if (total === 0) return { from: 0, to: 0, hasPrev: false, hasNext: false };
  return { from: offset + 1, to: Math.min(offset + limit, total), hasPrev: offset > 0, hasNext: offset + limit < total };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function snapshotLabel(s: Snapshot, latest: boolean): string {
  const t = new Date(s.as_of);
  const d = `${t.getUTCDate()} ${MONTHS[t.getUTCMonth()]} ${t.getUTCFullYear()}`; // fixed names: locale-independent
  return `${d} · ${s.scored.toLocaleString("en-US")} scored${latest ? " · latest" : ""}`;
}
