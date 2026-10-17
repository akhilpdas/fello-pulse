import { snapshotLabel } from "../lib/browse";
import type { Snapshots } from "../api/types";
import { useApi } from "../lib/useApi";

/** Which week's queue to look at. `value` is an `as_of` timestamp, or "" for the latest. */
export function WeekPicker({ value, onChange }: { value: string; onChange: (asOf: string) => void }) {
  const { data } = useApi((api) => api.get<Snapshots>("/queue/snapshots"));
  const snaps = data?.snapshots ?? [];
  if (snaps.length === 0) return null;
  return (
    <label className="filter">Week
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {snaps.map((s, i) => (
          <option key={s.as_of} value={i === 0 ? "" : s.as_of}>{snapshotLabel(s, i === 0)}</option>
        ))}
      </select>
    </label>
  );
}
