# Data model changes — migration `0005_auth_delivery_contacts`

All new tables carry `tenant_id`, are added to `TENANT_SCOPED_TABLES`, and get the same `FORCE`d RLS policy
as the rest (so the existing "unfiltered query returns zero foreign rows" isolation suite covers them once
the `two_tenants` fixture seeds a row in each).

## Changed tables

**`app_user`** + `password_hash text null` (scrypt, parameters embedded), `disabled_at timestamptz null`,
`password_changed_at timestamptz null`. A user with no hash cannot sign in. Unique `(tenant_id, email)`
already exists.

**`account`** + `contact_name text null`, `contact_email text null`. Never read by `features/`.

**`tenant_config`** + `outbound_enabled bool default false`, `sender_address text null`,
`sender_verified bool default false`, `demo_mode bool default true`, `test_inbox text null`,
`llm_calls_per_cycle int default 50`.

**`action`** + `redirected_to text null`, `provider_message_id text null`, `delivery_error text null`,
`original_subject text null`, `original_body text null` (what the model/template wrote before a human edit),
`draft_model text null`, `draft_fallback_reason text null`. States extend to: `sending`, `send_unconfirmed`,
`not_configured`, `outbound_disabled`, `no_recipient`, `opted_out` (existing: drafted, approved, rejected,
sent, send_failed).

**`feedback`**, **`suppression`**: no column change; they gain writers (Phase 0). `feedback.kind` values:
`false_positive`, `true_positive`, `not_actionable`.

## New tables

**`app_session`** `(id, tenant_id, user_id, token_hash char(64) unique, created_at, expires_at, revoked_at,
last_seen_at, user_agent)`. Index `(tenant_id, token_hash)`. Lookup is always under the tenant claim (R-2).

**`audit_event`** `(id, tenant_id, at, actor_user_id null, actor_kind {user|system|anonymous}, event
{login_ok|login_failed|logout|forbidden|tenant_mismatch|user_created|user_enabled|user_disabled|role_changed|password_reset|
outbound_changed|opt_out_added|opt_out_removed|cycle_run}, subject text null, detail jsonb)`. Append-only (no update/delete grant to
the app role).

**`contact_opt_out`** `(id, tenant_id, email lower, reason, created_by_user_id, created_at)` unique
`(tenant_id, email)`.

**`login_attempt`** `(id bigserial, key_hash char(64), at timestamptz)` — added by migration `0006` after the first design.
A **global** table (declared in `GLOBAL_TABLES`; no `tenant_id`, no RLS) because a sign-in has no tenant until it succeeds. It holds only a
hash of (address, workspace, email) — or of (address, `*`, `*`) for the per-source limit — and a time; purged as it ages.

## State transitions — `action.state`

```
drafted ──approve──▶ approved ──(send)──▶ sent
   │                    │            ├─ transient×3 ─▶ send_failed
   │                    │            ├─ permanent ───▶ send_failed
   │                    │            └─ ambiguous ───▶ send_unconfirmed   (never auto-retried)
   (approved→outcome happens inside one transaction, so `approved`/`sending` are never visible to another reader;
    approval is a single conditional UPDATE, which is what makes two simultaneous approvals send once.
    From send_failed, outbound_disabled, not_configured, no_recipient, opted_out an operator may approve again — the
    message definitely did not leave. From sent and send_unconfirmed they may not.)
   │                    └─ checks at send time ─▶ not_configured | outbound_disabled | no_recipient | opted_out
   └─reject─▶ rejected
```

Every terminal state carries `state_reason`; none is silently dropped (constitution III).

## Validation rules

- Password: ≥12 characters, not equal to the email, not in a small deny-list of common passwords.
- `sender_verified` can be set only by an operator; `outbound_enabled` cannot be turned on while
  `sender_address` is null or `sender_verified` is false.
- `suppression.expires_at` must be in the future when created; `reason` non-empty.
