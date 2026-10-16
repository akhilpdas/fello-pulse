"""The facts a drafted message may state (FR-024, FR-030). Pure.

A language model is handed *only* these short sentences -- derived deterministically from the numeric
features the system already computed for the account -- plus the account and CSM names. No ticket subject,
email body, CRM note or any other free text from a source ever reaches it: text a customer wrote is the
obvious place for an attacker to plant instructions, so it is never an input. The same list is stored on the
action (``grounding.facts``) and is what the model's output is validated against.
"""

from __future__ import annotations

from collections.abc import Callable

Values = dict


def _n(v: float) -> str:
    return str(int(round(v))) if abs(v - round(v)) < 1e-9 else f"{v:.1f}"


def _num(values: Values, key: str) -> float | None:
    v = values.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _positive(values: Values, key: str) -> float | None:
    v = _num(values, key)
    return v if v is not None and v > 0 else None


def _support(v: Values) -> list[str]:
    out: list[str] = []
    if (n := _positive(v, "support_tickets_28d")) is not None:
        out.append(f"{_n(n)} support ticket{'s' if round(n) != 1 else ''} in the last 28 days")
        if (p1 := _positive(v, "support_p1_tickets_28d")) is not None:
            out.append(f"{_n(p1)} of them {'was' if round(p1) == 1 else 'were'} urgent (P1)")
    if (h := _positive(v, "support_median_first_response_h_28d")) is not None:
        out.append(f"the median first response took {_n(h)} hours")
    if (r := _positive(v, "support_reopened_28d")) is not None:
        out.append(f"{_n(r)} ticket{'s' if round(r) != 1 else ''} had to be reopened")
    if (a := _positive(v, "support_max_unresolved_age_days")) is not None:
        out.append(f"the oldest open ticket is {_n(a)} days old")
    if (c := _positive(v, "support_negative_csat_share_90d")) is not None:
        out.append(f"{_n(c * 100)}% of recent satisfaction ratings were negative")
    return out


def _usage(v: Values) -> list[str]:
    out: list[str] = []
    users, seats = _num(v, "usage_active_users_28d"), _positive(v, "seats")
    if users is not None:
        out.append(f"{_n(users)} active user{'s' if round(users) != 1 else ''} in the last 28 days"
                   + (f", on {_n(seats)} seats" if seats is not None else ""))
    if (d := _positive(v, "usage_days_since_last_activity")) is not None:
        out.append(f"there has been no product activity for {_n(d)} days")
    if (c := _positive(v, "usage_champion_inactive_days")) is not None:
        out.append(f"your main champion has been inactive for {_n(c)} days")
    return out


def _billing(v: Values) -> list[str]:
    out: list[str] = []
    if (n := _positive(v, "billing_failed_payments_90d")) is not None:
        out.append(f"{_n(n)} payment{'s' if round(n) != 1 else ''} failed in the last 90 days")
    if v.get("billing_dunning_active") is True:
        out.append("a payment is currently being retried")
    if (late := _positive(v, "billing_invoice_days_late_mean_180d")) is not None:
        out.append(f"invoices have been paid {_n(late)} days late on average")
    return out


def _relationship(v: Values) -> list[str]:
    out: list[str] = []
    if (d := _positive(v, "crm_days_since_meeting")) is not None:
        out.append(f"the last logged meeting was {_n(d)} days ago")
    if v.get("crm_qbr_done_180d") is False:
        out.append("there has been no business review in the last 180 days")
    if (e := _positive(v, "email_days_since_customer_reply")) is not None:
        out.append(f"the last reply from your team was {_n(e)} days ago")
    return out


def _commercial(v: Values) -> list[str]:
    d = _num(v, "days_to_renewal")
    return [f"the renewal is in {_n(d)} days"] if d is not None and d >= 0 else []


_BY_DRIVER: dict[str, Callable[[Values], list[str]]] = {
    "support_experience": _support, "usage_decline": _usage, "payment_friction": _billing,
    "relationship_engagement": _relationship, "commercial_signals": _commercial,
}


def build_facts(driver: str, feature_values: Values) -> list[str]:
    """Plain sentences for one driver. An absent or zero value is omitted -- never guessed, never padded."""
    fn = _BY_DRIVER.get(driver)
    return fn(feature_values) if fn else []
