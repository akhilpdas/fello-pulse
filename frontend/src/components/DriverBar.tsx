import { driverLabel } from "../lib/format";

// Contributions are in log-odds and can be negative (a driver pulling risk down).
export function DriverBars({ totals }: { totals: Record<string, number> }) {
  const entries = Object.entries(totals).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const max = Math.max(...entries.map(([, v]) => Math.abs(v)), 1e-9);
  return (
    <div className="drivers">
      {entries.map(([driver, v]) => (
        <div className="driver-row" key={driver}>
          <span className="driver-name">{driverLabel(driver)}</span>
          <span className="driver-track">
            <span className={`driver-fill ${v >= 0 ? "up" : "down"}`} style={{ width: `${(Math.abs(v) / max) * 100}%` }} />
          </span>
          <span className="driver-val">{v >= 0 ? "+" : ""}{v.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}
