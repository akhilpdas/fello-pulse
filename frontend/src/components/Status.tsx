export function Status({ loading, error, empty }: { loading: boolean; error: string | null; empty?: string | false | null }) {
  if (loading) return <p className="muted">Loading…</p>;
  if (error) return <p className="error" role="alert">{error}</p>;
  if (empty) return <p className="muted">{empty}</p>;
  return null;
}
