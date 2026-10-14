"""The five source emitters.

Each source observes the same latent health process through its own noisy,
lagged, partially-missing lens. Nothing here reads the outcome to decide what to
emit — emitters see only the latent path, exactly as a real source system sees
only the customer's behaviour. The two exceptions are the cancellation record
and the Closed-Lost stage change, which are *mechanically* downstream of the
outcome and are precisely why the feature layer has a denylist.

Volume shape is a deliberate decision, recorded here because it is the kind of
thing a reviewer should push on:

Product usage is emitted as a **weekly rollup carrying a daily breakdown**, not
as raw per-day or per-session events. Raw telemetry for 5,000 accounts over
three years is hundreds of millions of rows, no product-analytics pipeline ships
that into a CS tool, and the feature layer would immediately aggregate it to
exactly this shape. The rollup is therefore both the realistic integration
contract and the honest scoping decision. The payload carries ``period_days`` so
the feature layer handles daily deliveries too, and a tenant on daily delivery
costs nothing to support.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import numpy as np

from simulate import SimResult
from spec import FEATURE_KEYS

# Emission rates, per account-week unless noted. Tuned so the estate lands near
# the brief's event budget without starving any single source of signal.
GMAIL_THREADS_PER_WEEK = 0.16
ZENDESK_TICKETS_PER_WEEK = 0.10
PRODUCT_ROLLUP_SKIP_WHEN_SILENT = True
SALESFORCE_REFRESH_DAYS = 115

# Product rollups arrive weekly for recent history and fortnightly for anything
# older. This is not an arbitrary saving: a backfilled history is routinely
# coarser than a live feed, and the resolution that matters is the recent window
# the live scoring features read. The payload carries ``period_days`` so the
# feature layer normalises both without special cases, and a tenant delivering
# daily costs nothing to support.
PRODUCT_FINE_WINDOW_DAYS = 183


@dataclass
class Record:
    """One record as a source system would hand it to us.

    ``received_at`` is deliberately absent: arrival time is not the source's
    property, it is ours, and ``pathologies.py`` assigns it. Keeping the two
    apart in the code mirrors the fact that they are different facts about the
    world.
    """

    source: str
    source_event_id: str
    event_type: str
    source_account_ref: str
    occurred_at: datetime
    payload: dict


def _dt(d: date, hour: int = 10, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=UTC)


# Holidays that visibly dent product usage. Their presence is the reason the
# feature layer must compare aligned whole weeks: a trailing 7-day window
# straddling one of these reports a "decline" for every healthy account.
def _is_holiday(d: date) -> bool:
    if d.month == 12 and d.day >= 22:
        return True
    if d.month == 1 and d.day <= 2:
        return True
    if d.month == 11 and 22 <= d.day <= 29 and d.weekday() in (3, 4):
        return True
    if d.month == 7 and d.day == 4:
        return True
    return False


def _seasonal_factor(d: date) -> float:
    """Weekday rhythm plus holidays. Strong enough to fool a naive feature."""
    wd = d.weekday()
    if wd == 5:
        return 0.22
    if wd == 6:
        return 0.15
    if _is_holiday(d):
        return 0.25
    if wd == 4:
        return 0.86
    return 1.0


# --------------------------------------------------------------------------- #
# Product
# --------------------------------------------------------------------------- #


def emit_product(sim: SimResult, rng: np.random.Generator) -> list[Record]:
    a = sim.account
    out: list[Record] = []
    n = len(sim.dates)

    # Week boundaries aligned to Monday, so the rollup periods line up with the
    # decision cadence and with the feature layer's aligned windows.
    start = sim.dates[0]
    first_monday = start + timedelta(days=(7 - start.weekday()) % 7)

    from simulate import DATASET_END

    week_start = first_monday
    while week_start <= sim.dates[-1]:
        idx0 = (week_start - start).days
        if idx0 >= n:
            break
        fine = (DATASET_END - week_start).days <= PRODUCT_FINE_WINDOW_DAYS
        period_days = 7 if fine else 14
        daily = []
        week_users: set[str] = set()
        total_sessions = 0
        feature_set: set[str] = set()

        for off in range(period_days):
            d = week_start + timedelta(days=off)
            i = idx0 + off
            if i >= n or d > sim.dates[-1]:
                break
            h = float(sim.health[i])
            season = _seasonal_factor(d)

            # Active users scale with seats and health. The exponent on health
            # makes the fall-off nonlinear: a drop from 0.8 to 0.6 costs less
            # than a drop from 0.4 to 0.2, which matches how usage collapses.
            lam = a.seats * 0.45 * (h ** 1.6) * season
            active = int(rng.poisson(max(lam, 0.02)))
            active = min(active, len(a.users))

            # Once the champion has gone, the single most active user is simply
            # absent. Usage does not just fall, its *shape* changes.
            if sim.champion_left and d >= sim.champion_left:
                active = max(0, active - 1)

            sessions = int(rng.poisson(max(active * (1.1 + 1.9 * h), 0.02)))
            breadth = int(np.clip(round(len(FEATURE_KEYS) * (0.22 + 0.62 * h)), 1, len(FEATURE_KEYS)))
            feats = list(rng.choice(FEATURE_KEYS, size=breadth, replace=False)) if active else []

            if active:
                chosen = list(rng.choice(a.users, size=min(active, len(a.users)), replace=False))
                week_users.update(chosen)
                feature_set.update(feats)
            total_sessions += sessions
            daily.append(
                {"date": d.isoformat(), "active_users": active, "sessions": sessions}
            )

        if PRODUCT_ROLLUP_SKIP_WHEN_SILENT and not week_users:
            # Silence is represented by the absence of a record, not by a row of
            # zeros. That is what a real pipeline does, and it forces the
            # feature layer to distinguish "no data" from "no activity".
            week_start += timedelta(days=period_days)
            continue

        out.append(
            Record(
                source="product",
                source_event_id=f"{a.product_ref}-wk-{week_start.isoformat()}",
                event_type="usage.weekly_rollup",
                source_account_ref=a.product_ref,
                occurred_at=_dt(week_start + timedelta(days=period_days), 3, 15),
                payload={
                    "period_start": week_start.isoformat(),
                    "period_days": period_days,
                    "active_users": len(week_users),
                    "sessions": total_sessions,
                    "feature_keys": sorted(feature_set),
                    # Nullable on purpose: seat counts are not always synced.
                    "seats_snapshot": a.seats if rng.random() > 0.12 else None,
                    "daily": daily,
                    "user_refs": sorted(week_users)[:25],
                },
            )
        )
        week_start += timedelta(days=period_days)

    # First-use milestones: adoption signal, and the hook the one allowlisted
    # autonomous play (the adoption nudge) keys off.
    seen: set[str] = set()
    for rec in out[:40]:
        for f in rec.payload["feature_keys"]:
            if f not in seen:
                seen.add(f)
                if rng.random() < 0.3:
                    out.append(
                        Record(
                            source="product",
                            source_event_id=f"{a.product_ref}-first-{f}",
                            event_type="feature.first_used",
                            source_account_ref=a.product_ref,
                            occurred_at=_dt(date.fromisoformat(rec.payload["period_start"]), 14),
                            payload={"feature_key": f},
                        )
                    )
    return out


# --------------------------------------------------------------------------- #
# Zendesk
# --------------------------------------------------------------------------- #


def emit_zendesk(sim: SimResult, rng: np.random.Generator) -> list[Record]:
    """Support activity.

    Two separate things live in here and the model needs to tell them apart:
    how much trouble the customer is having (ticket volume, priority) and how
    badly *we* are serving them (first-response time, reopens, unresolved age).
    The second is the one that makes automated cheerful outreach to a red
    account indefensible.
    """
    a = sim.account
    out: list[Record] = []
    n = len(sim.dates)
    weeks = max(1, n // 7)

    # Weeks in which our support was failing — response times blow out here.
    failure_windows = [
        (d, d + timedelta(days=35)) for (d, k) in sim.shocks if k == "support_failure"
    ]

    for w in range(weeks):
        idx = min(w * 7, n - 1)
        d0 = sim.dates[idx]
        h = float(sim.health[idx])
        # Unhappy accounts file more tickets, and bigger accounts file more of
        # them simply by having more people.
        lam = ZENDESK_TICKETS_PER_WEEK * (0.45 + 2.1 * (1.0 - h)) * math.log1p(a.seats) / 2.6
        for t in range(int(rng.poisson(max(lam, 0.0)))):
            created = d0 + timedelta(days=int(rng.integers(0, 7)))
            if created > sim.dates[-1]:
                continue
            tref = f"{a.zd_ref}-t{w:03d}{t}"
            in_failure = any(lo <= created <= hi for lo, hi in failure_windows)
            # Ticket timing is minute-resolution: date arithmetic would silently
            # round a 90-minute first response to zero days and destroy the
            # response-time feature, which is one of the strongest in the set.
            created_dt = _dt(created, int(rng.integers(8, 18)))

            p1 = rng.random() < (0.07 + 0.30 * (1.0 - h))
            priority = "urgent" if p1 and rng.random() < 0.4 else ("high" if p1 else
                       str(rng.choice(["normal", "low"], p=[0.7, 0.3])))
            out.append(
                Record("zendesk", f"{tref}-created", "ticket.created", a.zd_ref,
                       created_dt,
                       {"ticket_ref": tref, "priority": priority,
                        "subject": str(rng.choice(TICKET_SUBJECTS)),
                        "requester_ref": str(rng.choice(a.users))})
            )

            # First response. Lognormal, and far worse inside a failure window —
            # this is the feature that should dominate a support-driven red.
            base_mu = 1.5 if not in_failure else 3.1
            resp_min = float(np.clip(rng.lognormal(base_mu + 2.6, 0.9), 4, 60 * 96))
            replied = created_dt + timedelta(minutes=resp_min)
            if replied.date() <= sim.dates[-1] and rng.random() > 0.05:
                out.append(
                    Record("zendesk", f"{tref}-reply", "ticket.first_reply", a.zd_ref,
                           replied, {"ticket_ref": tref,
                                     "response_minutes": round(resp_min, 1)})
                )

            # Resolution. Some tickets are simply never solved, and an ageing
            # unresolved P1 is one of the strongest signals in the dataset.
            solve_p = 0.93 if not in_failure else 0.66
            if rng.random() < solve_p:
                res_min = resp_min * rng.uniform(1.4, 9.0)
                solved = created_dt + timedelta(minutes=res_min)
                if solved.date() <= sim.dates[-1]:
                    out.append(
                        Record("zendesk", f"{tref}-solved", "ticket.solved", a.zd_ref,
                               solved,
                               {"ticket_ref": tref, "resolution_minutes": round(res_min, 1)})
                    )
                    if rng.random() < (0.05 + 0.22 * (1.0 - h)):
                        re_at = solved + timedelta(days=int(rng.integers(1, 9)))
                        if re_at.date() <= sim.dates[-1]:
                            out.append(
                                Record("zendesk", f"{tref}-reopen", "ticket.reopened",
                                       a.zd_ref, _dt(re_at.date(), 9),
                                       {"ticket_ref": tref})
                            )
                    # CSAT is requested on every solved ticket and answered on
                    # roughly two thirds. The nulls are not missing at random:
                    # unhappy customers answer less, which is itself a signal
                    # and a trap for anyone who imputes the mean.
                    answered = rng.random() < (0.72 - 0.25 * (1.0 - h))
                    score = None
                    if answered:
                        good = rng.random() < (0.25 + 0.68 * h)
                        score = int(rng.integers(4, 6)) if good else int(rng.integers(1, 4))
                    out.append(
                        Record("zendesk", f"{tref}-csat", "satisfaction.rated", a.zd_ref,
                               _dt(solved.date(), 17),
                               {"ticket_ref": tref, "satisfaction_score": score})
                    )
    return out


TICKET_SUBJECTS = (
    "Export failing for large reports", "Cannot invite new team member",
    "Campaign send stuck in queue", "Dashboard numbers look wrong",
    "SSO login loop", "API rate limit questions", "Billing address update",
    "Mobile app crash on open", "Duplicate contacts after import",
    "Automation not triggering", "Integration disconnected overnight",
    "Request: bulk edit", "Slow page loads since Tuesday",
)


# --------------------------------------------------------------------------- #
# Gmail
# --------------------------------------------------------------------------- #


def emit_gmail(sim: SimResult, rng: np.random.Generator) -> list[Record]:
    """Relationship engagement.

    The signal that matters most here is not volume but *reciprocity*. An
    account where we send and they stop replying is disengaging, and the
    unanswered-outbound streak is often the earliest visible sign — earlier than
    usage, which decays slowly, and earlier than support, which may be silent.
    """
    a = sim.account
    out: list[Record] = []
    n = len(sim.dates)
    weeks = max(1, n // 7)

    for w in range(weeks):
        idx = min(w * 7, n - 1)
        d0 = sim.dates[idx]
        h = float(sim.health[idx])
        lam = GMAIL_THREADS_PER_WEEK * (0.3 + 1.5 * h)
        for t in range(int(rng.poisson(max(lam, 0.0)))):
            day = d0 + timedelta(days=int(rng.integers(0, 7)))
            if day > sim.dates[-1]:
                continue
            thread = f"thr-{a.external_ref}-{w:03d}{t}"
            participants = list(
                rng.choice(a.users, size=min(len(a.users), int(rng.integers(1, 4))), replace=False)
            )
            # The champion drops out of threads once they have left.
            if sim.champion_left and day >= sim.champion_left:
                participants = [p for p in participants if p != a.champion] or participants[:1]
            exec_on = bool(rng.random() < 0.08 + 0.22 * h)

            out.append(
                Record("gmail", f"{thread}-out", "message.sent", a.gmail_domain,
                       _dt(day, int(rng.integers(8, 17))),
                       {"thread_ref": thread, "direction": "outbound",
                        "participants": participants, "subject": str(rng.choice(EMAIL_SUBJECTS)),
                        "word_count": int(rng.integers(40, 320)),
                        "has_exec_participant": exec_on,
                        "sentiment": _sentiment(rng, h)})
            )

            # Do they reply, and how fast? Both degrade with health, and the
            # non-reply is modelled as an absent record rather than a zero.
            reply_p = 0.30 + 0.62 * h
            if rng.random() < reply_p:
                lag_days = float(np.clip(rng.lognormal(0.2 + 1.9 * (1.0 - h), 0.8), 0.05, 45))
                rday = day + timedelta(days=int(lag_days))
                if rday <= sim.dates[-1]:
                    out.append(
                        Record("gmail", f"{thread}-in", "message.received", a.gmail_domain,
                               _dt(rday, int(rng.integers(7, 20))),
                               {"thread_ref": thread, "direction": "inbound",
                                "participants": participants,
                                "subject": "Re: " + str(rng.choice(EMAIL_SUBJECTS)),
                                "word_count": int(rng.integers(12, 220)),
                                "has_exec_participant": exec_on,
                                "reply_lag_days": round(lag_days, 2),
                                "sentiment": _sentiment(rng, h)})
                    )
    return out


def _sentiment(rng: np.random.Generator, h: float) -> float | None:
    """Null about 22% of the time — the sentiment model does not always score."""
    if rng.random() < 0.22:
        return None
    return round(float(np.clip(rng.normal(-0.55 + 1.5 * h, 0.33), -1.0, 1.0)), 3)


EMAIL_SUBJECTS = (
    "Quick question on the rollout", "Following up on last week",
    "Renewal paperwork", "Training session scheduling", "Q3 usage summary",
    "Intro to our new ops lead", "Checking in", "Feature request follow-up",
    "Invoice query", "Onboarding next steps",
)


# --------------------------------------------------------------------------- #
# Stripe
# --------------------------------------------------------------------------- #


def emit_stripe(sim: SimResult, rng: np.random.Generator) -> list[Record]:
    a = sim.account
    out: list[Record] = []
    end = sim.outcome.at.date() if sim.outcome.at else sim.dates[-1]

    mrr_changes = dict(sim.mrr_history)
    current = sim.mrr_history[0][1]

    d = sim.dates[0]
    seq = 0
    while d <= end:
        if d in mrr_changes:
            prev, current = current, mrr_changes[d]
            out.append(
                Record("stripe", f"{a.stripe_ref}-sub-{seq}", "subscription.updated",
                       a.stripe_ref, _dt(d, 6),
                       {"subscription_ref": f"sub_{a.stripe_ref[4:]}", "mrr_cents": current,
                        "previous_mrr_cents": prev, "plan": _plan(a.segment)})
            )
        idx = min((d - sim.dates[0]).days, len(sim.health) - 1)
        h = float(sim.health[idx])

        # Payment friction rises as health falls. Partly causal (a disengaged
        # account stops chasing its own finance team) and partly coincidental —
        # which is realistic, and means the feature is useful but not decisive.
        fail_p = 0.012 + 0.085 * (1.0 - h) ** 2
        if rng.random() < fail_p:
            out.append(
                Record("stripe", f"{a.stripe_ref}-fail-{seq}", "invoice.payment_failed",
                       a.stripe_ref, _dt(d, 7),
                       {"invoice_ref": f"in_{a.stripe_ref[4:]}_{seq}", "amount_cents": current,
                        "attempt": int(rng.integers(1, 4))})
            )
            paid_late = rng.random() < 0.82
            if paid_late:
                pay_day = d + timedelta(days=int(rng.integers(2, 21)))
                if pay_day <= end:
                    out.append(
                        Record("stripe", f"{a.stripe_ref}-inv-{seq}", "invoice.paid",
                               a.stripe_ref, _dt(pay_day, 7),
                               {"invoice_ref": f"in_{a.stripe_ref[4:]}_{seq}",
                                "amount_cents": current, "due_at": _dt(d, 7).isoformat(),
                                "paid_at": _dt(pay_day, 7).isoformat()})
                    )
        else:
            # Healthy accounts pay close to the due date; struggling ones drift.
            late = int(np.clip(rng.lognormal(0.1 + 1.4 * (1.0 - h), 0.8) - 1, 0, 40))
            pay_day = d + timedelta(days=late)
            if pay_day <= end:
                out.append(
                    Record("stripe", f"{a.stripe_ref}-inv-{seq}", "invoice.paid",
                           a.stripe_ref, _dt(pay_day, 7),
                           {"invoice_ref": f"in_{a.stripe_ref[4:]}_{seq}",
                            "amount_cents": current, "due_at": _dt(d, 7).isoformat(),
                            "paid_at": _dt(pay_day, 7).isoformat()})
                )
        seq += 1
        d += timedelta(days=30)

    # DENYLISTED. Stored because labelling needs it and the evidence trail shows
    # it, but unreadable from feature code: it is the outcome, not a predictor.
    if sim.outcome.kind == "churn" and sim.outcome.at:
        out.append(
            Record("stripe", f"{a.stripe_ref}-cancel", "subscription.deleted", a.stripe_ref,
                   sim.outcome.at,
                   {"subscription_ref": f"sub_{a.stripe_ref[4:]}", "reason": sim.outcome.cause})
        )
    return out


def _plan(segment: str) -> str:
    return {"smb": "starter", "mid": "growth", "enterprise": "scale"}[segment]


# --------------------------------------------------------------------------- #
# Salesforce
# --------------------------------------------------------------------------- #


def emit_salesforce(sim: SimResult, rng: np.random.Generator) -> list[Record]:
    a = sim.account
    out: list[Record] = []
    end = sim.outcome.at.date() if sim.outcome.at else sim.dates[-1]

    owner = a.owner_ref
    d = sim.dates[0]
    seq = 0
    while d <= end:
        renewal = a.signup
        while renewal <= d:
            renewal += timedelta(days=365)
        out.append(
            Record("salesforce", f"{a.sf_ref}-acct-{seq}", "Account.updated", a.sf_ref,
                   _dt(d, 5),
                   {"name": a.name, "segment": a.segment, "industry": a.industry,
                    "region": a.region,
                    "seats": a.seats if rng.random() > 0.09 else None,
                    # ACV missing on ~7% of refreshes: the ranking must fall back
                    # to annualised billing rather than inventing a number.
                    "acv_cents": a.acv_cents if rng.random() > 0.07 else None,
                    "renewal_date": renewal.isoformat(),
                    "owner_ref": owner,
                    "plan": _plan(a.segment)})
        )
        seq += 1
        d += timedelta(days=SALESFORCE_REFRESH_DAYS)

    # Owner changes. A real churn driver on their side and ours, and a feature
    # a CSM can act on: nobody has owned this account for four months.
    years = max(0.2, (end - sim.dates[0]).days / 365.0)
    for _ in range(int(rng.poisson(0.25 * years))):
        when = sim.dates[0] + timedelta(days=int(rng.integers(30, max(31, (end - sim.dates[0]).days))))
        new_owner = owner[:-2] + f"{int(rng.integers(0, 24)):02d}"
        out.append(
            Record("salesforce", f"{a.sf_ref}-own-{when.isoformat()}", "Account.owner_changed",
                   a.sf_ref, _dt(when, 11),
                   {"from_owner_ref": owner, "to_owner_ref": new_owner})
        )
        owner = new_owner

    # Meetings: QBRs and check-ins. More of both when things are going well,
    # which makes "days since last meeting" informative and also slightly
    # confounded — a model should not treat it as decisive on its own.
    idx_end = len(sim.health) - 1
    cadence = {"enterprise": 70, "mid": 110, "smb": 190}[a.segment]
    when = sim.dates[0] + timedelta(days=int(rng.integers(20, 60)))
    while when <= end:
        i = min((when - sim.dates[0]).days, idx_end)
        if rng.random() < 0.35 + 0.55 * float(sim.health[i]):
            kind = str(rng.choice(["qbr", "checkin", "training"], p=[0.3, 0.55, 0.15]))
            out.append(
                Record("salesforce", f"{a.sf_ref}-mtg-{when.isoformat()}", "Task.logged",
                       a.sf_ref, _dt(when, 13),
                       {"kind": kind, "attendees": int(rng.integers(2, 7))})
            )
        when += timedelta(days=int(cadence * rng.uniform(0.7, 1.4)))

    # Renewal opportunities moving through stages.
    r = a.signup + timedelta(days=365)
    while r <= end + timedelta(days=120):
        opp = f"opp-{a.external_ref}-{r.year}"
        for offset, stage in ((-75, "Discovery"), (-45, "Proposal"), (-15, "Negotiation")):
            sd = r + timedelta(days=offset)
            if sim.dates[0] <= sd <= end:
                out.append(
                    Record("salesforce", f"{opp}-{stage}", "Opportunity.stage_changed", a.sf_ref,
                           _dt(sd, 12),
                           {"opportunity_ref": opp, "stage": stage,
                            "amount_cents": a.acv_cents})
                )
        r += timedelta(days=365)

    # DENYLISTED, same reasoning as subscription.deleted.
    if sim.outcome.kind == "churn" and sim.outcome.at:
        out.append(
            Record("salesforce", f"{a.sf_ref}-lost", "Opportunity.closed_lost", a.sf_ref,
                   sim.outcome.at,
                   {"opportunity_ref": f"opp-{a.external_ref}-final",
                    "stage": "Closed Lost", "amount_cents": a.acv_cents})
        )
    return out


EMITTERS = {
    "product": emit_product,
    "zendesk": emit_zendesk,
    "gmail": emit_gmail,
    "stripe": emit_stripe,
    "salesforce": emit_salesforce,
}
