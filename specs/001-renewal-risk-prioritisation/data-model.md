# Data Model

**Feature**: 001-renewal-risk-prioritisation | **Store**: PostgreSQL 16

## Conventions

- Primary keys are UUIDv4 unless stated. Natural keys are enforced with unique
  constraints alongside the surrogate key.
- Every tenant-scoped table carries `tenant_id uuid NOT NULL REFERENCES tenant(id)`,
  has `ENABLE ROW LEVEL SECURITY` **and** `FORCE ROW LEVEL SECURITY`, and a policy
  `USING (tenant_id = current_setting('pulse.tenant_id', true)::uuid)`. `FORCE` matters:
  without it the table owner silently bypasses the policy, which would make the
  isolation tests pass for the wrong reason.
- All timestamps are `timestamptz`, stored UTC. The application never reads the wall
  clock directly; a `Clock` is injected so that point-in-time behaviour is testable.
- `source_event.payload`, `feature_snapshot.values`, `score.contributions` and
  `score.ranking_math` are `jsonb`. Everything else is typed columns — JSONB is used
  for genuinely open-shaped data, not as an escape from schema design.

---

## Tenant and identity

### `tenant`
Not tenant-scoped; this is the scoping root.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `slug` | text UNIQUE NOT NULL | `northwind`, `globex`, `initech` |
| `name` | text NOT NULL | |
| `created_at` | timestamptz NOT NULL | |

### `tenant_config`
One row per tenant. Separate from `tenant` because it is written by operators at a
different cadence and every field here is an answer to an open business question.

| Column | Type | Default | Notes |
|---|---|---|---|
| `tenant_id` | uuid PK FK | | |
| `horizon_days` | int | 90 | label horizon (clarification B-1) |
| `contraction_threshold` | numeric | 0.25 | MRR drop counted as material loss (A1) |
| `weekly_capacity` | int | 10 | per-CSM queue bound (A3) |
| `tier_red_at` | numeric | 0.35 | calibrated probability thresholds |
| `tier_amber_at` | numeric | 0.15 | |
| `min_days_history` | int | 30 | below this → abstain (FR-026) |
| `min_sources_with_data` | int | 2 | below this → abstain |
| `suppression_days` | int | 14 | per-account contact cooldown (FR-035) |
| `max_sends_per_cycle` | int | 25 | per-tenant rate limit |
| `material_delta` | numeric | 0.08 | probability move that counts as change (B-9) |
| `connected_sources` | text[] | all five | a tenant may legitimately lack one |

### `app_user`
Tenant-scoped. A CSM or an operator.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | RLS |
| `email` | text NOT NULL | unique within tenant |
| `name` | text NOT NULL | |
| `role` | text NOT NULL | `csm` \| `operator` |

Unique: `(tenant_id, email)`.

---

## Accounts and source identity

### `account`
The unit that gets scored.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | RLS |
| `external_ref` | text NOT NULL | stable human-facing reference |
| `name` | text NOT NULL | |
| `segment` | text | `smb` \| `mid` \| `enterprise` |
| `industry` | text NULL | nullable on purpose: generator leaves ~6% unmapped |
| `region` | text NULL | |
| `seats` | int NULL | nullable: per-seat features must abstain, not divide by a guess |
| `acv_cents` | bigint NULL | NULL → fall back to annualised MRR, else unrankable-by-value (A2) |
| `mrr_cents` | bigint NULL | current, maintained by billing ingestion |
| `renewal_date` | date NULL | urgency term; NULL handled explicitly in ranking |
| `signup_date` | date NOT NULL | drives `account_age_days` and the cold-start path |
| `owner_user_id` | uuid FK NULL | the CSM whose queue this lands in (A5) |
| `lifecycle_state` | text NOT NULL | `active` \| `churned` \| `contracted` |
| `churned_at` | timestamptz NULL | **outcome column — denied to the feature layer** |

Unique: `(tenant_id, external_ref)`. Index: `(tenant_id, owner_user_id)`.

> `churned_at` and `lifecycle_state` are the label's raw material. They live on the
> account for convenience of labelling and reporting and are listed in
> `features/denylist.py` as unreadable from feature code. The leakage test asserts this.

### `identity_link`
Maps a source-native identifier to an internal account. Exists as its own table rather
than as columns on `account` because the mapping is incomplete in reality, and an
unresolved identifier needs somewhere to live and be visible (FR-006).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | RLS |
| `source` | text NOT NULL | `salesforce` \| `gmail` \| `zendesk` \| `product` \| `stripe` |
| `source_account_ref` | text NOT NULL | e.g. `cus_8f21a0` |
| `account_id` | uuid FK NULL | **NULL means unresolved and is a first-class state** |
| `method` | text NOT NULL | `direct` \| `mapping_table` \| `domain_match` \| `unresolved` |
| `confidence` | numeric NOT NULL | 1.0 for direct, lower for inferred |
| `first_seen_at` | timestamptz NOT NULL | |

Unique: `(tenant_id, source, source_account_ref)`.

---

## The event log

### `source_event`
Append-only. The single most important table in the system; everything else is derived
from it.

| Column | Type | Notes |
|---|---|---|
| `id` | bigserial PK | monotonic, gives a total order tiebreak when `occurred_at` ties |
| `tenant_id` | uuid FK | RLS |
| `source` | text NOT NULL | one of the five |
| `source_event_id` | text NOT NULL | the source's own id — the idempotency key |
| `event_type` | text NOT NULL | normalised internal type, not the source's spelling |
| `account_id` | uuid FK NULL | NULL when identity is unresolved |
| `source_account_ref` | text NOT NULL | retained even when resolved, for tracing |
| `occurred_at` | timestamptz NOT NULL | when it happened in the source |
| `received_at` | timestamptz NOT NULL | when Pulse durably stored it |
| `payload` | jsonb NOT NULL | the original record, unmodified, for the evidence trail |

Unique: `(tenant_id, source, source_event_id)` — this constraint *is* FR-003.

Indexes:
- `(tenant_id, account_id, received_at)` — the as-of query path. Every feature read
  filters `received_at <= as_of`, so this index carries the whole feature layer.
- `(tenant_id, account_id, event_type, received_at)` — per-feature windowed counts.
- `(tenant_id, source, received_at)` — watermark advancement and coverage reporting.

> Both timestamps are non-null and neither is derived from the other. A record whose
> `received_at` is three days after its `occurred_at` is the normal case, not an error,
> and it is the reason a score computed last Tuesday stays valid as a record of what
> was known last Tuesday.

### `ingestion_watermark`

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | uuid PK part FK | RLS |
| `source` | text PK part | |
| `last_received_at` | timestamptz NOT NULL | advanced only after durable write (FR-004) |
| `last_cursor` | text NULL | opaque source cursor |
| `updated_at` | timestamptz NOT NULL | |

---

## Features

### `feature_snapshot`
One row per `(account, as_of)`. Persisted rather than recomputed so that drift is
detectable from history and so an explanation can never disagree with the score that
used it.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | RLS |
| `account_id` | uuid FK NOT NULL | |
| `as_of` | timestamptz NOT NULL | the decision time |
| `values` | jsonb NOT NULL | `{feature_name: number \| null}` — null means *absent* |
| `evidence` | jsonb NOT NULL | `{driver: [source_event.id, ...]}` (FR-011) |
| `coverage` | jsonb NOT NULL | per-source `{has_data, last_event_days, event_count}` |
| `days_of_history` | int NOT NULL | |
| `feature_set_version` | text NOT NULL | registry version that produced it |
| `computed_at` | timestamptz NOT NULL | |

Unique: `(tenant_id, account_id, as_of, feature_set_version)`.

> `values` distinguishes `null` from `0.0` deliberately, and that distinction survives
> all the way into the model (FR-009). An account with no Gmail connection has
> `null` email features; an account whose customer has stopped replying has `0`. Those
> are opposite situations and a system that imputes zero cannot tell them apart.

### `model_version`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `version` | text UNIQUE NOT NULL | `m-20261015-a1b2c3` |
| `algorithm` | text NOT NULL | |
| `feature_set_version` | text NOT NULL | |
| `trained_at` | timestamptz NOT NULL | |
| `train_window_start/end` | timestamptz NOT NULL | |
| `horizon_days` | int NOT NULL | |
| `seed` | int NOT NULL | reproducibility (constitution: Determinism) |
| `data_version` | text NOT NULL | generator seed + config hash |
| `metrics` | jsonb NOT NULL | the model card: operating point, baselines, calibration, per-tenant, lead time |
| `artifact_path` | text NOT NULL | |
| `promoted` | bool NOT NULL | false unless it beat the heuristic baseline (FR-020) |

Not tenant-scoped: one shared model serves all tenants (clarification B-7), and
training is an explicitly elevated cross-tenant path (FR-040).

### `score`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | RLS |
| `account_id` | uuid FK NOT NULL | |
| `as_of` | timestamptz NOT NULL | |
| `model_version` | text NOT NULL FK | |
| `feature_snapshot_id` | uuid FK NOT NULL | the exact inputs |
| `probability` | numeric NOT NULL | calibrated |
| `probability_raw` | numeric NOT NULL | pre-calibration, kept for diagnosis |
| `tier` | text NOT NULL | `red` \| `amber` \| `green` \| `unknown` |
| `health_score` | int NOT NULL | 0–100 display transform (the VP's ask, D1) |
| `confidence` | text NOT NULL | `high` \| `medium` \| `low` \| `abstain` |
| `abstain_reason` | text NULL | machine-readable, e.g. `no_billing_identity` |
| `contributions` | jsonb NOT NULL | `{feature: shap_value}` plus per-driver sums |
| `value_at_risk_cents` | bigint NULL | |
| `urgency_multiplier` | numeric NOT NULL | from days-to-renewal |
| `priority` | numeric NOT NULL | the ranked quantity |
| `ranking_math` | jsonb NOT NULL | every factor and the arithmetic, for display (FR-023) |
| `created_at` | timestamptz NOT NULL | |

Unique: `(tenant_id, account_id, as_of)`. Index: `(tenant_id, as_of DESC, priority DESC)`.

> Scores are immutable rows, never updated. The history *is* the audit trail, and the
> feature-level diff between two of them (FR-027) is what answers "why did this move",
> which is the question the two lost renewals would have needed answered.

---

## The agent

### `play_allowlist`
A play is allowed to dispatch autonomously only if a row exists here. Absence of a row
is the default and means "draft for human approval" (FR-034).

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | uuid PK part FK | RLS |
| `play_key` | text PK part | |
| `auto_send` | bool NOT NULL | |
| `enabled_by_user_id` | uuid FK | who switched it on — this is an accountability record |
| `enabled_at` | timestamptz NOT NULL | |

### `action`
A selected play instance for an account.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | RLS |
| `account_id` | uuid FK NOT NULL | |
| `score_id` | uuid FK NOT NULL | the score that justified it |
| `play_key` | text NOT NULL | |
| `state` | text NOT NULL | `drafted` \| `pending_approval` \| `approved` \| `sent` \| `rejected` \| `suppressed` \| `failed` |
| `state_reason` | text NULL | why suppressed / why failed |
| `channel` | text NOT NULL | `email` \| `call_task` |
| `subject` | text NULL | |
| `body` | text NULL | |
| `draft_source` | text NOT NULL | `template` \| `llm` — so a reviewer knows which wrote it |
| `grounding` | jsonb NOT NULL | the evidence the draft was allowed to reference (FR-036) |
| `agent_run_id` | uuid FK | which cycle created it |
| `created_at` / `decided_at` / `sent_at` | timestamptz | |
| `decided_by_user_id` | uuid FK NULL | the actor on approve/reject (FR-046) |
| `attempts` | int NOT NULL | retry count for transport failures |

Index: `(tenant_id, account_id, created_at DESC)`, `(tenant_id, state)`.

### `agent_run`
One autonomous cycle (FR-031).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK NULL | NULL for the cross-tenant orchestration record |
| `trigger` | text NOT NULL | `schedule` \| `manual_backfill` — a manual run is labelled as such so the autonomy claim stays honest |
| `started_at` / `finished_at` | timestamptz | |
| `status` | text NOT NULL | `running` \| `succeeded` \| `failed` |
| `stage_counts` | jsonb NOT NULL | `{ingested, features_refreshed, scored, material_changes, plays_selected, drafted, sent}` |
| `decisions_declined` | jsonb NOT NULL | `[{account_id, play_key, reason}]` — **the suppressions and withholdings, which are the interesting half** |
| `errors` | jsonb NOT NULL | |
| `duration_ms` | int NULL | surfaced so a cycle creeping past its interval is visible |

> A cycle that did nothing still writes a row saying so. A monitoring surface that goes
> quiet when nothing happens is indistinguishable from one that has stopped working,
> and that distinction is the whole point of the run log.

### `work_lease`
Crash-safe claiming (FR-030).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `kind` | text NOT NULL | `tenant_cycle` \| `account_score` |
| `key` | text NOT NULL | |
| `owner` | text NULL | worker instance id |
| `leased_until` | timestamptz NULL | expiry — an expired lease is reclaimable |
| `state` | text NOT NULL | `pending` \| `leased` \| `done` \| `failed` |
| `attempts` | int NOT NULL | |
| `updated_at` | timestamptz NOT NULL | |

Unique: `(kind, key)`. Claimed with `FOR UPDATE SKIP LOCKED`.

Not tenant-scoped: the queue is infrastructure and is only ever touched by the worker
under the elevated session.

### `suppression`
A human deciding an account should not be surfaced (FR-048).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | RLS |
| `account_id` | uuid FK NOT NULL | |
| `reason` | text NOT NULL | |
| `created_by_user_id` | uuid FK | |
| `expires_at` | timestamptz NULL | NULL = indefinite |

> Suppression is an exclusion from the *queue*, never from scoring. The account keeps
> being scored and stays in the history; it is only hidden from the work list. An
> account being deliberately allowed to churn is a legitimate business state and
> deleting its data to express that would destroy the record.

### `feedback`
A human judgement retained for training (FR-047).

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `tenant_id` | uuid FK | RLS |
| `account_id` | uuid FK NOT NULL | |
| `score_id` | uuid FK NULL | |
| `kind` | text NOT NULL | `false_positive` \| `confirmed_risk` \| `draft_unusable` |
| `note` | text NULL | |
| `created_by_user_id` | uuid FK | |
| `created_at` | timestamptz NOT NULL | |

> A dismissal that only removes a row from a list throws away the most valuable label
> the system will ever be handed: a domain expert saying "this one is wrong". It is
> stored as a label, not as a UI state.

---

## Entity relationships

```text
tenant ─1:1─ tenant_config
  │
  ├─1:N─ app_user ──owns──┐
  ├─1:N─ account ◄────────┘
  │         ├─1:N─ identity_link        (account_id nullable → unresolved)
  │         ├─1:N─ source_event         (account_id nullable → unresolved)
  │         ├─1:N─ feature_snapshot ─1:N─ score ─1:N─ action
  │         ├─1:N─ suppression
  │         └─1:N─ feedback
  ├─1:N─ ingestion_watermark
  ├─1:N─ play_allowlist
  └─1:N─ agent_run ─1:N─ action

model_version ─1:N─ score            (global, not tenant-scoped)
work_lease                            (global, worker-only)
```

## Tenant-scoping summary

| Table | Tenant-scoped + RLS | Rationale |
|---|---|---|
| `tenant` | no | the scoping root |
| `tenant_config`, `app_user`, `account`, `identity_link`, `source_event`, `ingestion_watermark`, `feature_snapshot`, `score`, `play_allowlist`, `action`, `suppression`, `feedback` | **yes** | all customer data |
| `agent_run` | yes (nullable tenant) | per-tenant cycles are scoped; the orchestration record is global |
| `model_version` | no | one shared model (B-7); written only by the elevated training path |
| `work_lease` | no | worker infrastructure, never served to a request |


---

## Added by spec 002 (migrations `0005_auth_delivery`, `0006_login_attempt`)

The model above is the 001 schema. Spec 002 added, and `specs/002-production-readiness/data-model.md` is the detailed reference:

- **`app_user`** + `password_hash`, `disabled_at`, `password_changed_at` (scrypt hash with embedded parameters; NULL = cannot sign in).
- **`account`** + `contact_name`, `contact_email` (from the CRM's `primary_contact`; NULL = no known contact; never a feature).
- **`tenant_config`** + `outbound_enabled` (false), `sender_address`, `sender_verified` (false), `demo_mode` (true), `test_inbox`, `llm_calls_per_cycle` (50).
- **`action`** + `redirected_to`, `provider_message_id`, `delivery_error`, `original_subject`, `original_body`, `draft_model`, `draft_fallback_reason`;
  its `state` gained the outcomes `send_unconfirmed`, `not_configured`, `outbound_disabled`, `no_recipient`, `opted_out`.
- **New tenant-scoped tables (row-level security, FORCEd):** `app_session`, `audit_event` (append-only for the application role), `contact_opt_out`.
- **New *global* table (declared, not tenant-scoped):** `login_attempt` — a hash and a time, used by the shared login limiter.
