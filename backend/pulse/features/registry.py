"""The declarative feature registry: contracts/features.md as code.

Every feature is declared here -- name, driver group, window, the event types
it may read, and its absence rule -- rather than inlined into compute.py.
``compute.py`` asserts at import time that it has exactly one computation
function per entry here, in both directions, so the registry and the
computation code cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

USAGE_DECLINE = "usage_decline"
SUPPORT_EXPERIENCE = "support_experience"
RELATIONSHIP_ENGAGEMENT = "relationship_engagement"
PAYMENT_FRICTION = "payment_friction"
COMMERCIAL_SIGNALS = "commercial_signals"
DATA_QUALITY = "data_quality"

DRIVER_GROUPS: tuple[str, ...] = (
    USAGE_DECLINE, SUPPORT_EXPERIENCE, RELATIONSHIP_ENGAGEMENT,
    PAYMENT_FRICTION, COMMERCIAL_SIGNALS, DATA_QUALITY,
)

DRIVER_READS: dict[str, str] = {
    USAGE_DECLINE: "product",
    SUPPORT_EXPERIENCE: "zendesk",
    RELATIONSHIP_ENGAGEMENT: "gmail, salesforce meetings",
    PAYMENT_FRICTION: "stripe",
    COMMERCIAL_SIGNALS: "salesforce opportunities, contract terms",
    DATA_QUALITY: "coverage metadata across all sources",
}

ABSTAIN_REASONS: frozenset[str] = frozenset(
    {"insufficient_history", "insufficient_sources", "no_billing_identity"}
)


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    driver: str
    window: str
    readable_types: frozenset[str]
    absence_rule: str


def _spec(name: str, driver: str, window: str, readable_types: tuple[str, ...], absence_rule: str) -> FeatureSpec:
    return FeatureSpec(name, driver, window, frozenset(readable_types), absence_rule)


# NOTE: contracts/ingestion.md documents this as "product.usage_daily", but the
# already-shipped ProductAdapter (Phase 4) normalises both weekly and daily
# deliveries to "product.usage_rollup". Registry follows the real adapter
# output, not the stale doc string -- see clarifications.md.
_PRODUCT = ("product.usage_rollup", "product.feature_first_used")
_ZENDESK = (
    "support.ticket_created", "support.first_reply", "support.ticket_solved",
    "support.ticket_reopened", "support.satisfaction_rated",
)
_GMAIL = ("email.inbound", "email.outbound")
_CRM_MEETING = ("crm.meeting_logged",)
_STRIPE = ("billing.invoice_paid", "billing.payment_failed", "billing.subscription_updated")
_CRM_COMMERCIAL = ("crm.account_updated", "crm.opportunity_stage_changed", "crm.owner_changed")

REGISTRY: dict[str, FeatureSpec] = {
    f.name: f
    for f in [
        # usage_decline
        _spec("usage_active_users_28d", USAGE_DECLINE, "28d", _PRODUCT, "None if no usage events ever"),
        _spec("usage_active_users_wow", USAGE_DECLINE, "aligned_4w_wow", _PRODUCT, "None if either window lacks coverage"),
        _spec("usage_sessions_per_seat_28d", USAGE_DECLINE, "28d", _PRODUCT, "None if seats null in period"),
        _spec("usage_feature_breadth_28d", USAGE_DECLINE, "28d", _PRODUCT, "None if no usage events"),
        _spec("usage_days_since_last_activity", USAGE_DECLINE, "unbounded", _PRODUCT, "None if never active"),
        _spec("usage_dau_mau_28d", USAGE_DECLINE, "28d", _PRODUCT, "None if no usage events"),
        _spec("usage_seat_utilisation", USAGE_DECLINE, "28d", _PRODUCT, "None if seats null"),
        _spec("usage_champion_inactive_days", USAGE_DECLINE, "unbounded", _PRODUCT, "None if no identifiable champion"),
        # support_experience
        _spec("support_tickets_28d", SUPPORT_EXPERIENCE, "28d", _ZENDESK, "None if source not connected"),
        _spec("support_ticket_rate_28d_vs_90d", SUPPORT_EXPERIENCE, "ratio", _ZENDESK, "None if <90d history"),
        _spec("support_p1_tickets_28d", SUPPORT_EXPERIENCE, "28d", _ZENDESK, "None if source not connected"),
        _spec("support_median_first_response_h_28d", SUPPORT_EXPERIENCE, "28d", _ZENDESK, "None if no replies in window"),
        _spec("support_reopened_28d", SUPPORT_EXPERIENCE, "28d", _ZENDESK, "None if source not connected"),
        _spec("support_max_unresolved_age_days", SUPPORT_EXPERIENCE, "open tickets", _ZENDESK, "None if no open tickets"),
        _spec("support_negative_csat_share_90d", SUPPORT_EXPERIENCE, "90d", _ZENDESK, "None if no rated tickets"),
        # relationship_engagement
        _spec("email_inbound_28d", RELATIONSHIP_ENGAGEMENT, "28d", _GMAIL, "None if tenant has no gmail source"),
        _spec("email_days_since_customer_reply", RELATIONSHIP_ENGAGEMENT, "unbounded", _GMAIL, "None if never replied"),
        _spec("email_unanswered_outbound_streak", RELATIONSHIP_ENGAGEMENT, "consecutive", _GMAIL, "None if no outbound"),
        _spec("email_participant_count_delta_90d", RELATIONSHIP_ENGAGEMENT, "aligned", _GMAIL, "None if <90d of email"),
        _spec("email_exec_on_thread_90d", RELATIONSHIP_ENGAGEMENT, "90d", _GMAIL, "None if no email"),
        _spec("crm_days_since_meeting", RELATIONSHIP_ENGAGEMENT, "unbounded", _CRM_MEETING, "None if no meeting ever logged"),
        _spec("crm_qbr_done_180d", RELATIONSHIP_ENGAGEMENT, "180d", _CRM_MEETING, "None if source not connected"),
        _spec("crm_owner_changes_365d", RELATIONSHIP_ENGAGEMENT, "365d", ("crm.owner_changed",), "None if source not connected"),
        # payment_friction
        _spec("billing_failed_payments_90d", PAYMENT_FRICTION, "90d", _STRIPE, "None if no billing identity"),
        _spec("billing_dunning_active", PAYMENT_FRICTION, "current", _STRIPE, "None if no billing identity"),
        _spec("billing_invoice_days_late_mean_180d", PAYMENT_FRICTION, "180d", _STRIPE, "None if no paid invoices"),
        _spec("billing_mrr_change_90d", PAYMENT_FRICTION, "90d", _STRIPE, "None if <90d of billing"),
        _spec("billing_downgrades_365d", PAYMENT_FRICTION, "365d", _STRIPE, "None if no billing identity"),
        # commercial_signals
        _spec("days_to_renewal", COMMERCIAL_SIGNALS, "derived", _CRM_COMMERCIAL, "None if renewal_date null"),
        _spec("acv_cents", COMMERCIAL_SIGNALS, "current", _CRM_COMMERCIAL, "None if unknown"),
        _spec("account_age_days", COMMERCIAL_SIGNALS, "derived", (), "never None (signup_date mandatory)"),
        _spec("seats", COMMERCIAL_SIGNALS, "current", _CRM_COMMERCIAL, "None if unknown"),
        _spec("segment_ordinal", COMMERCIAL_SIGNALS, "current", _CRM_COMMERCIAL, "None if unknown"),
        _spec("open_opportunity_stage_ordinal", COMMERCIAL_SIGNALS, "current", _CRM_COMMERCIAL, "None if no open opportunity"),
        # data_quality
        _spec("cov_sources_with_data", DATA_QUALITY, "all-time", (), "0-5, never None"),
        _spec("cov_days_of_history", DATA_QUALITY, "all-time", (), "0 if no events ever"),
        _spec("cov_max_source_staleness_days", DATA_QUALITY, "all-time", (), "None if no connected sources"),
        _spec("cov_identity_unresolved", DATA_QUALITY, "current", (), "boolean, never None"),
    ]
}
