// Response bodies. The FastAPI routes return plain dicts, so the generated
// schema.d.ts types paths and request bodies but not these; they mirror the
// routers in backend/pulse/api/routers and are checked against live data.
export interface QueueRow {
  account_id: string; account_name: string; tier: string; health_score: number | null;
  probability: number; value_at_risk_cents: number | null; dominant_driver: string | null;
  days_to_renewal: number | null; priority: number; confidence: string;
  abstain_reason: string | null; delta: number | null;
}
export interface Queue { as_of: string | null; rows: QueueRow[]; below_cut: number }
export interface BrowseRow extends QueueRow { rank: number; in_queue: boolean }
export interface BrowseResult { as_of: string | null; rows: BrowseRow[]; total: number; offset: number; limit: number; capacity: number }
export interface Snapshot { as_of: string; scored: number }
export interface Snapshots { snapshots: Snapshot[] }
export interface LowConfidenceRow {
  account_id: string; account_name: string; abstain_reason: string;
  value_at_risk_cents: number | null; remedy: string;
}
export interface AccountDetail {
  account_id: string; account_name: string; as_of: string; tier: string; probability: number;
  confidence: string; abstain_reason: string | null; dominant_driver: string | null;
  driver_totals: Record<string, number>; value_at_risk_cents: number | null; priority: number;
  ranking_math: Record<string, number | null>;
  feature_values: Record<string, number | null>;
  evidence: Record<string, number[]>; coverage: Record<string, unknown>; days_of_history: number;
}
export interface SourceEvent {
  id: number; source: string; event_type: string; occurred_at: string; received_at: string;
  payload: Record<string, unknown>;
}
export interface FeatureDiff {
  feature: string; from_value: number | null; to_value: number | null; value_delta: number | null;
  from_contribution: number; to_contribution: number; contribution_delta: number;
}
export interface ScoreDiff {
  from: { as_of: string; probability: number; tier: string; dominant_driver: string | null };
  to: { as_of: string; probability: number; tier: string; dominant_driver: string | null };
  probability_delta: number; feature_diffs: FeatureDiff[];
}
export interface Action {
  id: string; account_id: string; play_key: string; state: string; state_reason: string | null;
  channel: string; subject: string | null; body: string; draft_source: string; created_at: string;
  decided_at: string | null; decided_by_user_id: string | null; sent_at: string | null;
  attempts: number; grounding: { evidence_drivers?: string[] } | null;
  redirected_to: string | null; provider_message_id: string | null; delivery_error: string | null;
  draft_model: string | null; draft_fallback_reason: string | null;
  original_subject: string | null; original_body: string | null;
}
export interface Run {
  id: string; trigger: string; status: string; started_at: string; finished_at: string | null;
  as_of: string; stage_counts: Record<string, number>;
  decisions_declined: { account_id?: string; play?: string; stage?: string; reason: string }[];
  errors: unknown[]; duration_ms: number | null;
}
