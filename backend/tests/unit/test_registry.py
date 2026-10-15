"""features/registry.py: every feature in contracts/features.md is declared,
and the two denylisted event types can never appear in a readable_types set --
the registry itself must not be the leak."""

from __future__ import annotations

from pulse.features.denylist import DENIED_EVENT_TYPES
from pulse.features.registry import DRIVER_GROUPS, REGISTRY, FeatureSpec


def test_registry_declares_every_contract_feature():
    expected = {
        "usage_active_users_28d", "usage_active_users_wow", "usage_sessions_per_seat_28d",
        "usage_feature_breadth_28d", "usage_days_since_last_activity", "usage_dau_mau_28d",
        "usage_seat_utilisation", "usage_champion_inactive_days",
        "support_tickets_28d", "support_ticket_rate_28d_vs_90d", "support_p1_tickets_28d",
        "support_median_first_response_h_28d", "support_reopened_28d",
        "support_max_unresolved_age_days", "support_negative_csat_share_90d",
        "email_inbound_28d", "email_days_since_customer_reply",
        "email_unanswered_outbound_streak", "email_participant_count_delta_90d",
        "email_exec_on_thread_90d", "crm_days_since_meeting", "crm_qbr_done_180d",
        "crm_owner_changes_365d",
        "billing_failed_payments_90d", "billing_dunning_active",
        "billing_invoice_days_late_mean_180d", "billing_mrr_change_90d",
        "billing_downgrades_365d",
        "days_to_renewal", "acv_cents", "account_age_days", "seats",
        "segment_ordinal", "open_opportunity_stage_ordinal",
        "cov_sources_with_data", "cov_days_of_history",
        "cov_max_source_staleness_days", "cov_identity_unresolved",
    }
    assert set(REGISTRY) == expected


def test_every_spec_belongs_to_a_known_driver_group():
    for spec in REGISTRY.values():
        assert isinstance(spec, FeatureSpec)
        assert spec.driver in DRIVER_GROUPS


def test_no_registered_feature_may_declare_a_denylisted_event_type_as_readable():
    for spec in REGISTRY.values():
        assert not (spec.readable_types & DENIED_EVENT_TYPES), spec.name
