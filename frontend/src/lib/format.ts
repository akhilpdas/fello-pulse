export function formatMoney(cents: number | null | undefined): string {
  if (cents == null) return "—";
  return "$" + Math.round(cents / 100).toLocaleString("en-US");
}

export function formatPercent(p: number): string {
  return (p * 100).toFixed(1) + "%";
}

export function formatDelta(delta: number | null | undefined): string {
  if (delta == null) return "new";
  const pts = delta * 100;
  if (Math.abs(pts) < 0.05) return "— flat";
  return `${pts > 0 ? "▲" : "▼"} ${Math.abs(pts).toFixed(1)} pts`;
}

export function renewalLabel(days: number | null | undefined): string {
  if (days == null) return "no renewal date";
  if (days < 0) return `${Math.abs(Math.round(days))} days overdue`;
  return `${Math.round(days)} days`;
}

export function driverLabel(driver: string | null | undefined): string {
  if (!driver) return "—";
  if (driver === "data_quality") return "Data quality (not customer behaviour)";
  return driver.charAt(0).toUpperCase() + driver.slice(1).replace(/_/g, " ");
}

const TIER_ORDER = ["red", "amber", "green", "abstain"];
export function tierRank(tier: string): number {
  const i = TIER_ORDER.indexOf(tier);
  return i === -1 ? TIER_ORDER.length : i;
}
