# Feature Registry Contract

Every feature is declared, not inlined. A declaration carries: name, driver group,
window, the event types it may read, its absence rule, and whether it is directional
(a delta) or a level.

Two rules are enforced by the registry rather than by convention:

1. **Absence is not zero.** A feature returns `None` when the evidence needed to
   compute it does not exist. It returns `0.0` only when the evidence exists and the
   count is genuinely zero. `email_inbound_28d` is `None` for a tenant with no Gmail
   connection and `0.0` for a customer who has gone silent — the model must be able to
   tell those apart (FR-009).
2. **Windows are weekday-aligned.** Any week-over-week comparison compares whole
   aligned weeks, never trailing 7-day windows offset by an arbitrary day. The
   generator injects weekday and holiday seasonality strong enough that a trailing
   window produces false positives every Monday; this is the test of whether the
   feature layer was written carefully.

## Driver groups

Six, in business language, because forty SHAP values is not an explanation (research 5).

| Driver | Reads from |
|---|---|
`usage_decline` | product |
`support_experience` | zendesk |
`relationship_engagement` | gmail, salesforce meetings |
`payment_friction` | stripe |
`commercial_signals` | salesforce opportunities, contract terms |
`data_quality` | coverage metadata across all sources |

## Features

### `usage_decline`
| Name | Window | Absence rule |
|---|---|---|
`usage_active_users_28d` | 28d | None if no usage events ever |
`usage_active_users_wow` | aligned 4w vs prior 4w, ratio | None if either window lacks coverage |
`usage_sessions_per_seat_28d` | 28d | None if `seats` null in period |
`usage_feature_breadth_28d` | 28d distinct feature keys | None if no usage events |
`usage_days_since_last_activity` | unbounded | None if never active |
`usage_dau_mau_28d` | 28d | None if no usage events |
`usage_seat_utilisation` | 28d active / seats | None if `seats` null |
`usage_champion_inactive_days` | top historical user | None if no identifiable champion |

### `support_experience`
| Name | Window | Absence rule |
|---|---|---|
`support_tickets_28d` | 28d | None if source not connected |
`support_ticket_rate_28d_vs_90d` | ratio | None if <90d history |
`support_p1_tickets_28d` | 28d | None if source not connected |
`support_median_first_response_h_28d` | 28d | None if no replies in window |
`support_reopened_28d` | 28d | None if source not connected |
`support_max_unresolved_age_days` | open tickets | None if no open tickets |
`support_negative_csat_share_90d` | 90d, nulls excluded | None if no rated tickets |

### `relationship_engagement`
| Name | Window | Absence rule |
|---|---|---|
`email_inbound_28d` | 28d | **None if tenant has no gmail source** |
`email_days_since_customer_reply` | unbounded | None if never replied |
`email_unanswered_outbound_streak` | consecutive | None if no outbound |
`email_participant_count_delta_90d` | aligned | None if <90d of email |
`email_exec_on_thread_90d` | 90d boolean | None if no email |
`crm_days_since_meeting` | unbounded | None if no meeting ever logged |
`crm_qbr_done_180d` | 180d boolean | None if source not connected |
`crm_owner_changes_365d` | 365d | None if source not connected |

### `payment_friction`
| Name | Window | Absence rule |
|---|---|---|
`billing_failed_payments_90d` | 90d | None if no billing identity |
`billing_dunning_active` | current | None if no billing identity |
`billing_invoice_days_late_mean_180d` | 180d | None if no paid invoices |
`billing_mrr_change_90d` | 90d ratio | None if <90d of billing |
`billing_downgrades_365d` | 365d | None if no billing identity |

### `commercial_signals`
| Name | Window | Absence rule |
|---|---|---|
`days_to_renewal` | derived | None if `renewal_date` null |
`acv_cents` | current | None if unknown (A2) |
`account_age_days` | derived | never None (`signup_date` mandatory) |
`seats` | current | None if unknown |
`segment_ordinal` | current | None if unknown |
`open_opportunity_stage_ordinal` | current | None if no open opportunity |

### `data_quality`
| Name | Notes |
|---|---|
`cov_sources_with_data` | 0–5 |
`cov_days_of_history` | from first event |
`cov_max_source_staleness_days` | worst per-source recency |
`cov_identity_unresolved` | boolean |

These are both model inputs and the basis of the abstain rule. A feature that is
`None` because the customer has no billing identity is a *data* problem, and the
explanation must say so rather than blaming the customer (spec edge case).

## Abstain rule

A score is `abstain` when `cov_days_of_history < tenant_config.min_days_history`, or
`cov_sources_with_data < tenant_config.min_sources_with_data`, or
`cov_identity_unresolved` is true. The reason is recorded machine-readably
(`insufficient_history`, `insufficient_sources`, `no_billing_identity`) so the UI can
state the remedy rather than showing a shrug (FR-026).
