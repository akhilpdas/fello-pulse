"""The feature engine. A pure function over an in-memory event list.

``compute()`` does no I/O. The same code path builds both the historical
training panel (ml/panel.py) and the live scoring path (scoring/service.py) --
the only real defense against train/serve skew (tests/unit/test_train_serve_parity.py).
Loading an account's events from the database and handing them here is a
separate, thin adapter used by both callers.

Point-in-time commercial attributes (segment, seats, acv_cents, renewal_date)
are deliberately *not* read from the account dimension row -- see
``ingest/dimension.py``'s own warning against that -- but derived here from the
latest ``crm.account_updated`` event with ``received_at <= as_of``. The only
account fact trusted directly from the dimension is ``signup_date``, which is
time-invariant and therefore safe.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from pulse.features.denylist import AccountFeatureInput, filter_denied_events
from pulse.features.registry import REGISTRY
from pulse.features.windows import aligned_window, week_over_week

SEGMENT_ORDINAL = {"smb": 0, "mid": 1, "enterprise": 2}
STAGE_ORDINAL = {"Discovery": 0, "Proposal": 1, "Negotiation": 2}

_PRODUCT_TYPES = frozenset({"product.usage_rollup", "product.feature_first_used"})
_ZENDESK_TYPES = frozenset({
    "support.ticket_created", "support.first_reply", "support.ticket_solved",
    "support.ticket_reopened", "support.satisfaction_rated",
})
_GMAIL_TYPES = frozenset({"email.inbound", "email.outbound"})
_STRIPE_TYPES = frozenset({"billing.invoice_paid", "billing.payment_failed", "billing.subscription_updated"})
_SF_COMMERCIAL_TYPES = frozenset({"crm.account_updated", "crm.opportunity_stage_changed", "crm.owner_changed"})

_SOURCE_TYPES = {
    "product": _PRODUCT_TYPES,
    "zendesk": _ZENDESK_TYPES,
    "gmail": _GMAIL_TYPES,
    "stripe": _STRIPE_TYPES,
    "salesforce": _SF_COMMERCIAL_TYPES | frozenset({"crm.meeting_logged"}),
}


@dataclass(frozen=True, slots=True)
class EventRecord:
    """A SourceEvent, shaped for the feature engine. ``id`` is carried through
    so evidence can point back at the exact record that produced a value."""

    id: int
    source: str
    event_type: str
    occurred_at: datetime
    received_at: datetime
    payload: dict


@dataclass(frozen=True, slots=True)
class FeatureResult:
    values: dict[str, object]
    evidence: dict[str, list[int]]
    coverage: dict[str, dict]
    days_of_history: int


class _Ctx:
    """Working state for one compute() call: filtered events, and the
    evidence accumulator every per-feature helper writes into."""

    def __init__(self, events: list[EventRecord], as_of: datetime, identity_unresolved: bool = False):
        self.as_of = as_of
        self.events = events
        self.identity_unresolved = identity_unresolved
        self.evidence: dict[str, set[int]] = defaultdict(set)

    def by_type(self, *types: str) -> list[EventRecord]:
        wanted = set(types)
        return [e for e in self.events if e.event_type in wanted]

    def mark(self, driver: str, events: list[EventRecord]) -> None:
        self.evidence[driver].update(e.id for e in events)

    def in_window(self, events: list[EventRecord], days: int) -> list[EventRecord]:
        start, end = aligned_window(self.as_of, days)
        return [e for e in events if start <= e.received_at < end]

    def in_range(self, events: list[EventRecord], start: datetime, end: datetime) -> list[EventRecord]:
        return [e for e in events if start <= e.received_at < end]


def compute(
    *,
    connected_sources: frozenset[str],
    account: AccountFeatureInput,
    events: list[EventRecord],
    as_of: datetime,
    identity_unresolved: bool = False,
) -> FeatureResult:
    # Defense in depth: never trust the caller to have pre-filtered. Both of
    # these are load-bearing, not redundant -- a denylisted event that arrives
    # before as_of must still be invisible to feature code.
    safe_events = filter_denied_events([e for e in events if e.received_at <= as_of])
    ctx = _Ctx(safe_events, as_of, identity_unresolved)

    values: dict[str, object] = {}
    for name in REGISTRY:
        values[name] = _COMPUTERS[name](ctx, connected_sources, account)

    coverage = _coverage(ctx, connected_sources)
    days_of_history = values["cov_days_of_history"]

    return FeatureResult(
        values=values,
        evidence={k: sorted(v) for k, v in ctx.evidence.items()},
        coverage=coverage,
        days_of_history=days_of_history,
    )


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _latest_account_update(ctx: _Ctx) -> EventRecord | None:
    updates = ctx.by_type("crm.account_updated")
    if not updates:
        return None
    return max(updates, key=lambda e: (e.received_at, e.id))


def _commercial_field(ctx: _Ctx, field: str):
    latest = _latest_account_update(ctx)
    if latest is None:
        return None
    ctx.mark("commercial_signals", [latest])
    val = latest.payload.get(field)
    return val


def _daily_entries(ctx: _Ctx, rollups: list[EventRecord]) -> list[tuple[date, int, EventRecord]]:
    """Flatten each rollup's ``daily`` breakdown into (date, active_users, source_event)."""
    out = []
    for r in rollups:
        for d in r.payload.get("daily", []):
            out.append((date.fromisoformat(d["date"]), int(d["active_users"]), r))
    return out


def _rollups_in_range(ctx: _Ctx, start: datetime, end: datetime) -> list[EventRecord]:
    """Rollups whose period overlaps [start, end), judged by received_at
    (point-in-time, already enforced by ctx.events) and by the period's own
    calendar span (relevance)."""
    out = []
    for r in _usage_rollups_all(ctx):
        if r.received_at >= end:
            continue
        p_start = date.fromisoformat(r.payload["period_start"])
        p_days = int(r.payload.get("period_days", 7))
        p_end = p_start + _td(p_days)
        if p_end > start.date() and p_start < end.date():
            out.append(r)
    return out


def _td(days: int):
    from datetime import timedelta
    return timedelta(days=days)


# --------------------------------------------------------------------------- #
# usage_decline
# --------------------------------------------------------------------------- #


def _usage_rollups_all(ctx: _Ctx) -> list[EventRecord]:
    return [e for e in ctx.events if e.event_type == "product.usage_rollup"]


def _daily_mean_in_window(ctx: _Ctx, start: datetime, end: datetime) -> tuple[float | None, list[EventRecord]]:
    rollups = _rollups_in_range(ctx, start, end)
    entries = [
        (d, au, src) for (d, au, src) in _daily_entries(ctx, rollups)
        if start.date() <= d < end.date()
    ]
    if not entries:
        return None, []
    mean = statistics.mean(au for _, au, _ in entries)
    touched = list({id(src): src for _, _, src in entries}.values())
    return mean, touched


def _f_usage_active_users_28d(ctx, connected, account):
    start, end = aligned_window(ctx.as_of, 28)
    if not _usage_rollups_all(ctx):
        return None
    mean, touched = _daily_mean_in_window(ctx, start, end)
    ctx.mark("usage_decline", touched)
    return mean if mean is not None else 0.0


def _f_usage_active_users_wow(ctx, connected, account):
    if not _usage_rollups_all(ctx):
        return None
    (cur_start, cur_end), (prior_start, prior_end) = week_over_week(ctx.as_of, weeks=4)
    cur_mean, cur_touched = _daily_mean_in_window(ctx, cur_start, cur_end)
    prior_mean, prior_touched = _daily_mean_in_window(ctx, prior_start, prior_end)
    if cur_mean is None or prior_mean is None:
        return None
    ctx.mark("usage_decline", cur_touched + prior_touched)
    if prior_mean == 0:
        return None
    return cur_mean / prior_mean


def _f_usage_sessions_per_seat_28d(ctx, connected, account):
    seats = _commercial_field(ctx, "seats")
    if seats in (None, 0):
        return None
    start, end = aligned_window(ctx.as_of, 28)
    rollups = _rollups_in_range(ctx, start, end)
    if not rollups:
        return None if not _usage_rollups_all(ctx) else 0.0
    total_sessions = sum(int(r.payload.get("sessions", 0)) for r in rollups)
    ctx.mark("usage_decline", rollups)
    return total_sessions / seats


def _f_usage_feature_breadth_28d(ctx, connected, account):
    if not _usage_rollups_all(ctx):
        return None
    start, end = aligned_window(ctx.as_of, 28)
    rollups = _rollups_in_range(ctx, start, end)
    ctx.mark("usage_decline", rollups)
    keys: set[str] = set()
    for r in rollups:
        keys.update(r.payload.get("feature_keys", []))
    return float(len(keys))


def _f_usage_days_since_last_activity(ctx, connected, account):
    rollups = _usage_rollups_all(ctx)
    if not rollups:
        return None
    entries = [(d, au, src) for (d, au, src) in _daily_entries(ctx, rollups) if au > 0]
    if not entries:
        return None
    last_date, _, last_src = max(entries, key=lambda t: t[0])
    ctx.mark("usage_decline", [last_src])
    return float((ctx.as_of.date() - last_date).days)


def _f_usage_dau_mau_28d(ctx, connected, account):
    if not _usage_rollups_all(ctx):
        return None
    start, end = aligned_window(ctx.as_of, 28)
    dau, touched = _daily_mean_in_window(ctx, start, end)
    rollups = _rollups_in_range(ctx, start, end)
    mau_users: set[str] = set()
    for r in rollups:
        mau_users.update(r.payload.get("user_refs", []))
    ctx.mark("usage_decline", touched + rollups)
    if not mau_users or dau is None:
        return None
    return dau / len(mau_users)


def _f_usage_seat_utilisation(ctx, connected, account):
    seats = _commercial_field(ctx, "seats")
    if seats in (None, 0):
        return None
    start, end = aligned_window(ctx.as_of, 28)
    dau, touched = _daily_mean_in_window(ctx, start, end)
    if dau is None:
        return None if not _usage_rollups_all(ctx) else 0.0
    ctx.mark("usage_decline", touched)
    return dau / seats


def _f_usage_champion_inactive_days(ctx, connected, account):
    rollups = _usage_rollups_all(ctx)
    appearances: Counter[str] = Counter()
    last_seen: dict[str, tuple[date, EventRecord]] = {}
    rollups_with_refs = 0
    for r in rollups:
        refs = r.payload.get("user_refs", [])
        if not refs:
            continue
        rollups_with_refs += 1
        p_end = date.fromisoformat(r.payload["period_start"]) + _td(int(r.payload.get("period_days", 7)))
        for ref in refs:
            appearances[ref] += 1
            if ref not in last_seen or p_end > last_seen[ref][0]:
                last_seen[ref] = (p_end, r)
    if rollups_with_refs < 2 or not appearances:
        return None
    champion = appearances.most_common(1)[0][0]
    last_date, src = last_seen[champion]
    ctx.mark("usage_decline", [src])
    return float((ctx.as_of.date() - last_date).days)


# --------------------------------------------------------------------------- #
# support_experience
# --------------------------------------------------------------------------- #


def _f_support_tickets_28d(ctx, connected, account):
    if "zendesk" not in connected:
        return None
    window = ctx.in_window(ctx.by_type("support.ticket_created"), 28)
    ctx.mark("support_experience", window)
    return float(len(window))


def _f_support_ticket_rate_28d_vs_90d(ctx, connected, account):
    created = ctx.by_type("support.ticket_created")
    if not created:
        return None
    first_ever = min(e.occurred_at for e in created)
    if (ctx.as_of - first_ever).days < 90:
        return None
    w28 = ctx.in_window(created, 28)
    start90, end90 = aligned_window(ctx.as_of, 91)  # nearest multiple of 7 >= 90
    w90 = ctx.in_range(created, start90, end90)
    ctx.mark("support_experience", w28 + w90)
    rate28 = len(w28) / 28.0
    rate90 = len(w90) / 91.0
    if rate90 == 0:
        return None
    return rate28 / rate90


def _f_support_p1_tickets_28d(ctx, connected, account):
    if "zendesk" not in connected:
        return None
    window = ctx.in_window(ctx.by_type("support.ticket_created"), 28)
    p1 = [e for e in window if e.payload.get("priority") in ("urgent", "high")]
    ctx.mark("support_experience", p1)
    return float(len(p1))


def _f_support_median_first_response_h_28d(ctx, connected, account):
    window = ctx.in_window(ctx.by_type("support.first_reply"), 28)
    if not window:
        return None
    ctx.mark("support_experience", window)
    minutes = [float(e.payload["response_minutes"]) for e in window]
    return statistics.median(minutes) / 60.0


def _f_support_reopened_28d(ctx, connected, account):
    if "zendesk" not in connected:
        return None
    window = ctx.in_window(ctx.by_type("support.ticket_reopened"), 28)
    ctx.mark("support_experience", window)
    return float(len(window))


def _f_support_max_unresolved_age_days(ctx, connected, account):
    created = ctx.by_type("support.ticket_created")
    solved_refs = {e.payload["ticket_ref"] for e in ctx.by_type("support.ticket_solved")}
    open_tickets = [e for e in created if e.payload["ticket_ref"] not in solved_refs]
    if not open_tickets:
        return None
    oldest = min(open_tickets, key=lambda e: e.occurred_at)
    ctx.mark("support_experience", [oldest])
    return float((ctx.as_of.date() - oldest.occurred_at.date()).days)


def _f_support_negative_csat_share_90d(ctx, connected, account):
    start, end = aligned_window(ctx.as_of, 91)
    window = ctx.in_range(ctx.by_type("support.satisfaction_rated"), start, end)
    rated = [e for e in window if e.payload.get("satisfaction_score") is not None]
    if not rated:
        return None
    ctx.mark("support_experience", rated)
    negative = sum(1 for e in rated if e.payload["satisfaction_score"] <= 2)
    return negative / len(rated)


# --------------------------------------------------------------------------- #
# relationship_engagement
# --------------------------------------------------------------------------- #


def _f_email_inbound_28d(ctx, connected, account):
    if "gmail" not in connected:
        return None
    window = ctx.in_window(ctx.by_type("email.inbound"), 28)
    ctx.mark("relationship_engagement", window)
    return float(len(window))


def _f_email_days_since_customer_reply(ctx, connected, account):
    inbound = ctx.by_type("email.inbound")
    if not inbound:
        return None
    last = max(inbound, key=lambda e: e.occurred_at)
    ctx.mark("relationship_engagement", [last])
    return float((ctx.as_of.date() - last.occurred_at.date()).days)


def _f_email_unanswered_outbound_streak(ctx, connected, account):
    outbound = ctx.by_type("email.outbound")
    if not outbound:
        return None
    inbound = ctx.by_type("email.inbound")
    cutoff = max((e.occurred_at for e in inbound), default=None)
    if cutoff is None:
        streak = outbound
    else:
        streak = [e for e in outbound if e.occurred_at > cutoff]
    ctx.mark("relationship_engagement", streak)
    return float(len(streak))


def _f_email_participant_count_delta_90d(ctx, connected, account):
    all_email = ctx.by_type("email.inbound", "email.outbound")
    if not all_email:
        return None
    first_ever = min(e.occurred_at for e in all_email)
    if (ctx.as_of - first_ever).days < 90:
        return None
    cur_start, cur_end = aligned_window(ctx.as_of, 91)
    prior_start, prior_end = aligned_window(cur_start, 91)
    cur = ctx.in_range(all_email, cur_start, cur_end)
    prior = ctx.in_range(all_email, prior_start, prior_end)
    ctx.mark("relationship_engagement", cur + prior)
    if not cur or not prior:
        return None
    cur_avg = statistics.mean(len(e.payload.get("participants", [])) for e in cur)
    prior_avg = statistics.mean(len(e.payload.get("participants", [])) for e in prior)
    return cur_avg - prior_avg


def _f_email_exec_on_thread_90d(ctx, connected, account):
    all_email = ctx.by_type("email.inbound", "email.outbound")
    if not all_email:
        return None
    start, end = aligned_window(ctx.as_of, 91)
    window = ctx.in_range(all_email, start, end)
    ctx.mark("relationship_engagement", window)
    return any(e.payload.get("has_exec_participant") for e in window)


def _f_crm_days_since_meeting(ctx, connected, account):
    meetings = ctx.by_type("crm.meeting_logged")
    if not meetings:
        return None
    last = max(meetings, key=lambda e: e.occurred_at)
    ctx.mark("relationship_engagement", [last])
    return float((ctx.as_of.date() - last.occurred_at.date()).days)


def _f_crm_qbr_done_180d(ctx, connected, account):
    if "salesforce" not in connected:
        return None
    start, end = aligned_window(ctx.as_of, 182)
    window = [e for e in ctx.in_range(ctx.by_type("crm.meeting_logged"), start, end)
              if e.payload.get("kind") == "qbr"]
    ctx.mark("relationship_engagement", window)
    return len(window) > 0


def _f_crm_owner_changes_365d(ctx, connected, account):
    if "salesforce" not in connected:
        return None
    start, end = aligned_window(ctx.as_of, 364)
    window = ctx.in_range(ctx.by_type("crm.owner_changed"), start, end)
    ctx.mark("relationship_engagement", window)
    return float(len(window))


# --------------------------------------------------------------------------- #
# payment_friction
# --------------------------------------------------------------------------- #


def _stripe_events(ctx: _Ctx) -> list[EventRecord]:
    return [e for e in ctx.events if e.source == "stripe"]


def _f_billing_failed_payments_90d(ctx, connected, account):
    if not _stripe_events(ctx):
        return None
    start, end = aligned_window(ctx.as_of, 91)
    window = ctx.in_range(ctx.by_type("billing.payment_failed"), start, end)
    ctx.mark("payment_friction", window)
    return float(len(window))


def _f_billing_dunning_active(ctx, connected, account):
    if not _stripe_events(ctx):
        return None
    failed = ctx.by_type("billing.payment_failed")
    paid_refs = {e.payload["invoice_ref"] for e in ctx.by_type("billing.invoice_paid")}
    unresolved = [e for e in failed if e.payload["invoice_ref"] not in paid_refs]
    ctx.mark("payment_friction", unresolved)
    return len(unresolved) > 0


def _f_billing_invoice_days_late_mean_180d(ctx, connected, account):
    start, end = aligned_window(ctx.as_of, 182)
    window = ctx.in_range(ctx.by_type("billing.invoice_paid"), start, end)
    valid = [e for e in window if e.payload.get("due_at") and e.payload.get("paid_at")]
    if not valid:
        return None
    ctx.mark("payment_friction", valid)
    days_late = [
        (datetime.fromisoformat(e.payload["paid_at"]) - datetime.fromisoformat(e.payload["due_at"])).days
        for e in valid
    ]
    return statistics.mean(days_late)


def _f_billing_mrr_change_90d(ctx, connected, account):
    updates = ctx.by_type("billing.subscription_updated")
    if not updates:
        return None
    first_ever = min(e.occurred_at for e in updates)
    if (ctx.as_of - first_ever).days < 90:
        return None
    latest = max(updates, key=lambda e: e.received_at)
    cutoff = ctx.as_of - _td(90)
    before = [e for e in updates if e.received_at <= cutoff]
    if not before:
        return None
    baseline = max(before, key=lambda e: e.received_at)
    ctx.mark("payment_friction", [latest, baseline])
    base_mrr = baseline.payload.get("mrr_cents")
    cur_mrr = latest.payload.get("mrr_cents")
    if not base_mrr:
        return None
    return cur_mrr / base_mrr


def _f_billing_downgrades_365d(ctx, connected, account):
    if not _stripe_events(ctx):
        return None
    start, end = aligned_window(ctx.as_of, 364)
    window = ctx.in_range(ctx.by_type("billing.subscription_updated"), start, end)
    downgrades = [
        e for e in window
        if e.payload.get("previous_mrr_cents") and e.payload.get("mrr_cents", 0) < e.payload["previous_mrr_cents"]
    ]
    ctx.mark("payment_friction", downgrades)
    return float(len(downgrades))


# --------------------------------------------------------------------------- #
# commercial_signals
# --------------------------------------------------------------------------- #


def _f_days_to_renewal(ctx, connected, account):
    renewal_raw = _commercial_field(ctx, "renewal_date")
    if renewal_raw is None:
        return None
    renewal = date.fromisoformat(renewal_raw) if isinstance(renewal_raw, str) else renewal_raw
    return float((renewal - ctx.as_of.date()).days)


def _f_acv_cents(ctx, connected, account):
    return _commercial_field(ctx, "acv_cents")


def _f_account_age_days(ctx, connected, account):
    return float((ctx.as_of.date() - account.signup_date).days)


def _f_seats(ctx, connected, account):
    return _commercial_field(ctx, "seats")


def _f_segment_ordinal(ctx, connected, account):
    segment = _commercial_field(ctx, "segment")
    if segment is None:
        return None
    return SEGMENT_ORDINAL.get(segment)


def _f_open_opportunity_stage_ordinal(ctx, connected, account):
    stage_events = ctx.by_type("crm.opportunity_stage_changed")
    if not stage_events:
        return None
    latest_per_opp: dict[str, EventRecord] = {}
    for e in stage_events:
        ref = e.payload["opportunity_ref"]
        if ref not in latest_per_opp or e.received_at > latest_per_opp[ref].received_at:
            latest_per_opp[ref] = e
    most_recent_opp = max(latest_per_opp.values(), key=lambda e: e.occurred_at)
    stage = most_recent_opp.payload.get("stage")
    ordinal = STAGE_ORDINAL.get(stage)
    if ordinal is None:
        return None
    ctx.mark("commercial_signals", [most_recent_opp])
    return ordinal


# --------------------------------------------------------------------------- #
# data_quality
# --------------------------------------------------------------------------- #

_ALL_SOURCES = ("product", "zendesk", "gmail", "stripe", "salesforce")


def _f_cov_sources_with_data(ctx, connected, account):
    seen = {e.source for e in ctx.events}
    return float(len(seen & connected & set(_ALL_SOURCES)))


def _f_cov_days_of_history(ctx, connected, account):
    if not ctx.events:
        return 0.0
    earliest = min(e.occurred_at for e in ctx.events)
    return float((ctx.as_of.date() - earliest.date()).days)


def _f_cov_max_source_staleness_days(ctx, connected, account):
    relevant = connected & set(_ALL_SOURCES)
    if not relevant:
        return None
    worst = 0.0
    history = _f_cov_days_of_history(ctx, connected, account)
    for source in relevant:
        source_events = [e for e in ctx.events if e.source == source]
        if not source_events:
            worst = max(worst, history)
            continue
        latest = max(e.occurred_at for e in source_events)
        worst = max(worst, (ctx.as_of.date() - latest.date()).days)
    return float(worst)


def _f_cov_identity_unresolved(ctx, connected, account):
    return bool(getattr(ctx, "identity_unresolved", False))


def _coverage(ctx: _Ctx, connected: frozenset[str]) -> dict[str, dict]:
    out = {}
    for source in _ALL_SOURCES:
        source_events = [e for e in ctx.events if e.source == source]
        out[source] = {
            "connected": source in connected,
            "has_data": bool(source_events),
            "last_event_days_ago": (
                (ctx.as_of.date() - max(e.occurred_at for e in source_events).date()).days
                if source_events else None
            ),
        }
    return out


_COMPUTERS = {
    "usage_active_users_28d": _f_usage_active_users_28d,
    "usage_active_users_wow": _f_usage_active_users_wow,
    "usage_sessions_per_seat_28d": _f_usage_sessions_per_seat_28d,
    "usage_feature_breadth_28d": _f_usage_feature_breadth_28d,
    "usage_days_since_last_activity": _f_usage_days_since_last_activity,
    "usage_dau_mau_28d": _f_usage_dau_mau_28d,
    "usage_seat_utilisation": _f_usage_seat_utilisation,
    "usage_champion_inactive_days": _f_usage_champion_inactive_days,
    "support_tickets_28d": _f_support_tickets_28d,
    "support_ticket_rate_28d_vs_90d": _f_support_ticket_rate_28d_vs_90d,
    "support_p1_tickets_28d": _f_support_p1_tickets_28d,
    "support_median_first_response_h_28d": _f_support_median_first_response_h_28d,
    "support_reopened_28d": _f_support_reopened_28d,
    "support_max_unresolved_age_days": _f_support_max_unresolved_age_days,
    "support_negative_csat_share_90d": _f_support_negative_csat_share_90d,
    "email_inbound_28d": _f_email_inbound_28d,
    "email_days_since_customer_reply": _f_email_days_since_customer_reply,
    "email_unanswered_outbound_streak": _f_email_unanswered_outbound_streak,
    "email_participant_count_delta_90d": _f_email_participant_count_delta_90d,
    "email_exec_on_thread_90d": _f_email_exec_on_thread_90d,
    "crm_days_since_meeting": _f_crm_days_since_meeting,
    "crm_qbr_done_180d": _f_crm_qbr_done_180d,
    "crm_owner_changes_365d": _f_crm_owner_changes_365d,
    "billing_failed_payments_90d": _f_billing_failed_payments_90d,
    "billing_dunning_active": _f_billing_dunning_active,
    "billing_invoice_days_late_mean_180d": _f_billing_invoice_days_late_mean_180d,
    "billing_mrr_change_90d": _f_billing_mrr_change_90d,
    "billing_downgrades_365d": _f_billing_downgrades_365d,
    "days_to_renewal": _f_days_to_renewal,
    "acv_cents": _f_acv_cents,
    "account_age_days": _f_account_age_days,
    "seats": _f_seats,
    "segment_ordinal": _f_segment_ordinal,
    "open_opportunity_stage_ordinal": _f_open_opportunity_stage_ordinal,
    "cov_sources_with_data": _f_cov_sources_with_data,
    "cov_days_of_history": _f_cov_days_of_history,
    "cov_max_source_staleness_days": _f_cov_max_source_staleness_days,
    "cov_identity_unresolved": _f_cov_identity_unresolved,
}

# Anti-drift guarantee: registry.py and compute.py cannot silently diverge.
assert set(_COMPUTERS) == set(REGISTRY), (
    f"compute.py/registry.py drift: {set(_COMPUTERS) ^ set(REGISTRY)}"
)
