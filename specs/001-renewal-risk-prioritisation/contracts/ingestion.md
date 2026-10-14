# Ingestion Contracts

The five source families. The generator writes these as newline-delimited JSON under
`data/feeds/<tenant_slug>/<source>.jsonl`; the adapters read them. This is the only
interface between the simulator and the application — the generator is never imported
by backend code.

## Envelope (every record, every source)

```json
{
  "source_event_id": "zd-tkt-91244-created",
  "source_account_ref": "zdorg_4471",
  "event_type": "<source-native type string>",
  "occurred_at": "2025-03-04T09:12:44+00:00",
  "received_at": "2025-03-06T02:15:00+00:00",
  "payload": { }
}
```

- `source_event_id` is the idempotency key. The generator re-emits ~0.6% of records
  with the same id to exercise FR-003.
- `received_at >= occurred_at` always, with a per-source lag distribution. Records are
  **not** written in `occurred_at` order; they are written in `received_at` order,
  which is the order a real poller would see them, and it means out-of-order arrival is
  the default case rather than an injected anomaly.
- `source_account_ref` is source-native. Resolution to an internal account is the
  adapter's job and may fail (FR-006).

## Normalised event types

Adapters map source-native types to the internal vocabulary. The internal type is what
features key on, so a source renaming its spelling must not reach the feature layer.

| Source | Source-native | Internal `event_type` |
|---|---|---|
| salesforce | `Account.updated`, `Account.Updated` | `crm.account_updated` |
| salesforce | `Opportunity.stage_changed` | `crm.opportunity_stage_changed` |
| salesforce | `Account.owner_changed` | `crm.owner_changed` |
| salesforce | `Task.logged` (meeting/QBR) | `crm.meeting_logged` |
| salesforce | `Opportunity.closed_lost` | `crm.closed_lost` ⛔ **denylisted** |
| gmail | `message.received` | `email.inbound` |
| gmail | `message.sent` | `email.outbound` |
| zendesk | `ticket.created` | `support.ticket_created` |
| zendesk | `ticket.first_reply` | `support.first_reply` |
| zendesk | `ticket.solved` | `support.ticket_solved` |
| zendesk | `ticket.reopened` | `support.ticket_reopened` |
| zendesk | `satisfaction.rated` | `support.satisfaction_rated` |
| product | `usage.daily_rollup` | `product.usage_daily` |
| product | `feature.first_used` | `product.feature_first_used` |
| stripe | `invoice.paid` | `billing.invoice_paid` |
| stripe | `invoice.payment_failed` | `billing.payment_failed` |
| stripe | `subscription.updated` | `billing.subscription_updated` |
| stripe | `subscription.deleted` | `billing.subscription_deleted` ⛔ **denylisted** |

⛔ Denylisted types are stored (they are needed for labelling and for the evidence
trail) but are unreadable from feature code (FR-010).

## Deliberate pathologies

Each exists because a requirement claims to handle it.

| Pathology | Shape in the feed | Requirement |
|---|---|---|
| Delivery lag, heavy-tailed | per-source lognormal; Zendesk webhook replays up to 5 days late | FR-005 |
| Out-of-order arrival | feeds ordered by `received_at`, so `occurred_at` goes backwards | FR-005, SC-009 |
| Duplicate delivery | ~0.6% of records emitted twice with identical `source_event_id` | FR-003 |
| Backfill burst | one tenant receives 6 months of Zendesk history in a single late batch | FR-004 edge case |
| Schema drift | `payload.plan` renamed to `payload.plan_name` after 2025-01-01; both appear in history | FR-007 |
| Case drift | Salesforce emits `Account.updated` before 2024-06-01 and `Account.Updated` after | FR-007 |
| Missing fields | `satisfaction_score`, `seats`, `industry` null at stated rates | FR-009 |
| Unresolved identity | ~3% of `source_account_ref` values have no mapping-table entry | FR-006 |
| Cold start | ~8% of accounts have <30 days of history; ~4% have only a CRM row | FR-026 |
| Missing source per tenant | `globex` emits no Gmail feed at all | US5, FR-012 |
| Seasonality | weekday/weekend and holiday dips in `product.usage_daily` | aligned-window features |
| Mixed offsets | `occurred_at` emitted with non-UTC offsets, normalised on read | — |

## Per-source payloads

**salesforce** — `crm.account_updated`: `{name, segment, industry?, region?, seats?,
acv_cents?, renewal_date?, owner_ref?, plan | plan_name}`.
`crm.opportunity_stage_changed`: `{opportunity_ref, stage, amount_cents}`.
`crm.owner_changed`: `{from_owner_ref, to_owner_ref}`.
`crm.meeting_logged`: `{kind: "qbr"|"checkin"|"training", attendees}`.

**gmail** — `{thread_ref, direction, participants[], subject, sentiment?,
word_count, has_exec_participant}`. `sentiment` null ~22% of the time.

**zendesk** — `support.ticket_created`: `{ticket_ref, priority, subject, requester_ref}`.
`support.first_reply`: `{ticket_ref, response_minutes}`.
`support.ticket_solved`: `{ticket_ref, resolution_minutes}`.
`support.satisfaction_rated`: `{ticket_ref, satisfaction_score?}` (null ~35%).

**product** — `product.usage_daily`: `{date, active_users, sessions, feature_keys[],
seats_snapshot?}`. One record per account-day where there was any activity; silence is
represented by absence, which is the realistic contract and forces the feature layer to
handle gaps rather than read zeros.

**stripe** — `billing.invoice_paid`: `{invoice_ref, amount_cents, due_at, paid_at}`.
`billing.payment_failed`: `{invoice_ref, amount_cents, attempt}`.
`billing.subscription_updated`: `{subscription_ref, mrr_cents, previous_mrr_cents, plan | plan_name}`.
