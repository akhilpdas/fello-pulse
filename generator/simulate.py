"""The latent health process, and the outcomes drawn from it.

Why a latent-state simulation rather than sampling features and labelling them
--------------------------------------------------------------------------
A generator that draws feature values and then assigns a label as a function of
those values produces a dataset where the model's task is to invert a formula.
It will score extremely well and prove nothing, because the mapping it has to
learn is the one that was just written down.

Here, each account carries an unobserved health process. Every source emits
noisy, lagged observations of it, and the churn decision is drawn from it. The
features and the label therefore share a *cause* rather than one being derived
from the other, so the model's task is inference under noise — the task it will
actually have. It also means the achievable ceiling is bounded by the noise we
inject rather than by the model, which is what makes the reported numbers
believable.

Three noise sources are deliberate and non-negotiable:

1. **Observation noise.** Every emitter samples around the latent state, so no
   single feature reveals it.
2. **Exogenous churn.** A fixed hazard of loss for reasons the data cannot
   contain — an acquisition, a budget cut, a new CFO. No feature predicts these
   and no model should.
3. **Survival despite poor health.** The churn draw is probabilistic, so
   unhealthy accounts frequently renew. Without this the label would be nearly a
   threshold on the latent state and the problem would collapse to a trivial one.

Together these cap achievable ROC-AUC far lower than first estimated. This
docstring once said "low-to-mid 0.8s"; measuring it (clarifications B-33) showed
that was wrong: a predictor that is *given* each account's hidden health scores
about 0.65-0.70 ROC-AUC per out-of-sample fold, because half of all losses are
contractions or exogenous churn and an unhealthy account usually survives its
renewal anyway. A backtest reporting 0.97 on data like this would be evidence of
a broken harness, and ``tests/unit/test_performance_plausibility.py`` fails the
build if it happens.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import numpy as np

from spec import (
    ACV_PER_SEAT,
    COMPANY_PREFIXES,
    COMPANY_SUFFIXES,
    INDUSTRIES,
    REGIONS,
    SEAT_LOGNORM,
    SEGMENTS,
    SHOCKS,
    AccountSpec,
    Outcome,
    TenantSpec,
)

# The dataset's "now": a Monday, because the product runs on a weekly cadence
# and every panel snapshot is taken on a Monday.
DATASET_END = date(2026, 10, 12)

# Mean-reversion parameters for the daily latent walk.
KAPPA = 0.013          # pull toward the account's own baseline
SIGMA = 0.020          # daily volatility
H_FLOOR, H_CEIL = 0.02, 0.985

# Annual churn rates by segment at average health. Smaller accounts churn more:
# less switching cost, less procurement friction, less relationship.
SEGMENT_BASE_CHURN = {"smb": 0.20, "mid": 0.12, "enterprise": 0.07}

# How sharply health translates into churn probability. Higher means the signal
# is more learnable; too high and the label becomes a threshold on h.
CHURN_SLOPE = 6.5
CHURN_PIVOT = 0.52

# Loss for reasons no feature can contain. This is the irreducible error, and it
# is the honest reason the model will never reach the high 0.9s.
EXOGENOUS_ANNUAL_CHURN = 0.028

# Hazard of a material contraction (>=25% MRR cut) off the renewal cycle.
CONTRACTION_ANNUAL_RATE = 0.075


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class SimResult:
    account: AccountSpec
    dates: list[date]
    health: np.ndarray
    shocks: list[tuple[date, str]]
    outcome: Outcome
    champion_left: date | None
    mrr_history: list[tuple[date, int]]   # (date, new mrr) at each change
    retro_label: str | None = None        # the planted retrospective fixtures
    meta: dict = field(default_factory=dict)


def build_accounts(tenant: TenantSpec, rng: np.random.Generator) -> list[AccountSpec]:
    """Create the account roster for one tenant.

    Signup dates follow compound growth rather than a uniform spread. A real
    SaaS signs up more customers this month than it did two years ago, so the
    age distribution is skewed young with a long tail. That is also why "three
    years of history" in the brief does not mean three years *per account* — and
    it is what makes the cold-start path a routine case rather than an edge one.
    """
    months = tenant.history_months
    weights = np.array([(1.0 + tenant.signup_growth) ** i for i in range(months)])
    weights = weights / weights.sum()

    accounts: list[AccountSpec] = []
    owners = [f"{tenant.slug}-csm-{i:02d}" for i in range(tenant.n_csms)]

    for i in range(tenant.n_accounts):
        months_ago = months - 1 - int(rng.choice(months, p=weights))
        jitter = int(rng.integers(0, 28))
        signup = DATASET_END - timedelta(days=months_ago * 30 + jitter)

        segment = str(rng.choice(SEGMENTS, p=tenant.segment_weights))
        mu_s, sigma_s = SEAT_LOGNORM[segment]
        seats = int(np.clip(rng.lognormal(mu_s, sigma_s), 2, 4000))
        acv = int(seats * ACV_PER_SEAT[segment] * rng.uniform(0.75, 1.35))

        # ~6% of accounts have no industry mapped. Real CRMs are like this, and
        # a feature that one-hot encodes industry must cope.
        industry = None if rng.random() < 0.06 else str(rng.choice(INDUSTRIES))
        region = None if rng.random() < 0.03 else str(rng.choice(REGIONS))

        name = (
            f"{rng.choice(COMPANY_PREFIXES)} {rng.choice(COMPANY_SUFFIXES)}"
            f"{'' if rng.random() < 0.75 else ' ' + str(int(rng.integers(2, 99)))}"
        )
        ref = f"{tenant.slug}-{i:05d}"

        n_users = int(np.clip(round(seats * rng.uniform(0.35, 0.9)), 1, 60))
        users = [f"{ref}-u{j:03d}" for j in range(n_users)]

        accounts.append(
            AccountSpec(
                tenant_slug=tenant.slug, index=i, external_ref=ref, name=name,
                segment=segment, industry=industry, region=region, seats=seats,
                acv_cents=acv, signup=signup,
                owner_ref=str(rng.choice(owners)),
                users=users, champion=users[0],
                # Five systems, five unrelated identifier schemes. The join
                # between them is a mapping table, and it is not complete.
                sf_ref=f"001{rng.integers(10**11, 10**12 - 1)}",
                zd_ref=f"zdorg_{rng.integers(100000, 999999)}",
                stripe_ref=f"cus_{''.join(rng.choice(list('abcdefghijklmnopqrstuvwxyz0123456789'), 14))}",
                gmail_domain=f"{ref.replace('-', '')}.example.com",
                product_ref=f"pw_{rng.integers(10**7, 10**8 - 1)}",
                **_contact(ref),
            )
        )
    return accounts


_FIRST = ["Alex", "Maria", "Chen", "Priya", "Tom", "Aisha", "Luca", "Hana", "Omar", "Sofia", "Ravi",
          "Elena", "Kofi", "Mei", "Jonas", "Amara", "Diego", "Ingrid", "Yusuf", "Nora"]
_LAST = ["Nguyen", "Okafor", "Rossi", "Patel", "Kim", "Silva", "Muller", "Haddad", "Ivanov", "Santos",
         "Larsen", "Abara", "Tanaka", "Costa", "Novak", "Reyes", "Berg", "Kaya", "Dubois", "Singh"]


def _contact(ref: str) -> dict:
    """The account's primary contact, derived from its reference alone.

    Deliberately *not* drawn from the estate's main random stream: adding a field must not shift one
    random number that decides an event, a lag or an outcome, or every downstream metric changes for
    reasons unrelated to the change. A hash-seeded stream per account keeps the rest of the estate
    byte-identical and the contact stable for the same account across runs.
    """
    r = np.random.default_rng(int.from_bytes(hashlib.sha256(f"contact:{ref}".encode()).digest()[:8], "big"))
    if r.random() >= 0.9:
        return {"contact_name": "", "contact_email": ""}
    first, last = str(r.choice(_FIRST)), str(r.choice(_LAST))
    return {"contact_name": f"{first} {last}",
            "contact_email": f"{first}.{last}@{ref.replace('-', '')}.example.com".lower()}


def simulate_account(
    acct: AccountSpec, rng: np.random.Generator, retro: str | None = None
) -> SimResult:
    """Walk one account's latent health and decide what happened to it."""
    n_days = (DATASET_END - acct.signup).days + 1
    dates = [acct.signup + timedelta(days=d) for d in range(n_days)]

    # Baseline health the account reverts to. Enterprise accounts start and stay
    # a little healthier: more onboarding, more investment, more switching cost.
    seg_lift = {"smb": -0.04, "mid": 0.0, "enterprise": 0.05}[acct.segment]
    mu = float(np.clip(rng.normal(0.70 + seg_lift, 0.085), 0.25, 0.92))
    h = float(np.clip(rng.normal(mu + 0.06, 0.05), 0.3, 0.95))  # onboarding optimism

    # A minority are on a slow secular decline that no single event explains —
    # the hardest kind to catch, and the kind the VP lost two renewals to.
    secular = -rng.uniform(0.04, 0.14) / 365.0 if rng.random() < 0.18 else 0.0

    health = np.empty(n_days, dtype=np.float64)
    shocks: list[tuple[date, str]] = []
    champion_left: date | None = None

    # Pre-draw shock days per shock type from a Poisson process.
    shock_days: dict[int, list[str]] = {}
    years = n_days / 365.0
    for s in SHOCKS:
        count = rng.poisson(s.annual_rate * years)
        for _ in range(int(count)):
            day = int(rng.integers(0, n_days))
            shock_days.setdefault(day, []).append(s.key)

    if retro == "slow_support_decline":
        # Planted fixture A: the quiet one. A string of support failures over
        # five months with no single dramatic event. This is what "nobody saw it
        # coming" looks like in the data.
        for k in range(5):
            day = max(0, n_days - 150 + k * 28)
            shock_days.setdefault(day, []).append("support_failure")
        secular = -0.16 / 365.0
    elif retro == "champion_collapse":
        # Planted fixture B: the fast one. The champion leaves ten weeks out and
        # usage falls off a cliff.
        shock_days.setdefault(max(0, n_days - 72), []).append("champion_departure")

    by_key = {s.key: s for s in SHOCKS}
    noise = rng.normal(0.0, SIGMA, n_days)

    for d in range(n_days):
        for key in shock_days.get(d, []):
            s = by_key[key]
            h += s.magnitude
            mu = float(np.clip(mu + s.magnitude * s.persistence, 0.10, 0.95))
            shocks.append((dates[d], key))
            if key == "champion_departure" and champion_left is None:
                champion_left = dates[d]
            if s.recoverable:
                # Recoverable shocks let the baseline drift back over months.
                mu = float(np.clip(mu + abs(s.magnitude) * s.persistence * 0.35, 0.10, 0.95))

        mu += secular
        h += KAPPA * (mu - h) + noise[d]
        h = float(np.clip(h, H_FLOOR, H_CEIL))
        health[d] = h

    outcome, mrr_history = _decide_outcome(acct, dates, health, shocks, rng, retro)
    return SimResult(
        account=acct, dates=dates, health=health, shocks=shocks, outcome=outcome,
        champion_left=champion_left, mrr_history=mrr_history, retro_label=retro,
        meta={"mu_final": mu, "secular_per_year": secular * 365.0},
    )


def _mean_health_before(health: np.ndarray, idx: int, days: int = 90) -> float:
    lo = max(0, idx - days)
    if idx <= lo:
        return float(health[0])
    return float(health[lo:idx].mean())


def _decide_outcome(
    acct: AccountSpec,
    dates: list[date],
    health: np.ndarray,
    shocks: list[tuple[date, str]],
    rng: np.random.Generator,
    retro: str | None,
) -> tuple[Outcome, list[tuple[date, int]]]:
    """Draw churn and contraction events from the latent path.

    Renewal risk concentrates at the anniversary, which is why the ranking layer
    carries an explicit urgency term — but contraction happens off-cycle, which
    is why the model's target is not conditioned on being near a renewal.
    """
    n = len(dates)
    base_mrr = acct.acv_cents // 12
    mrr_history: list[tuple[date, int]] = [(dates[0], base_mrr)]
    current_mrr = base_mrr

    seg_offset = _logit(SEGMENT_BASE_CHURN[acct.segment])
    exo_daily = EXOGENOUS_ANNUAL_CHURN / 365.0
    contraction_daily = CONTRACTION_ANNUAL_RATE / 365.0

    anniversaries = {
        (dates[0] + timedelta(days=365 * k)) for k in range(1, 4)
    }

    for idx in range(30, n):
        day = dates[idx]

        # Loss we could never have predicted. Keeps the ceiling honest.
        if rng.random() < exo_daily:
            return Outcome("churn", _dt(day), "exogenous"), mrr_history

        if day in anniversaries:
            hbar = _mean_health_before(health, idx)
            p = _sigmoid(CHURN_SLOPE * (CHURN_PIVOT - hbar) + seg_offset)
            if retro and idx > n - 120:
                p = max(p, 0.93)  # the planted fixtures do churn
            if rng.random() < p:
                return Outcome("churn", _dt(day), _dominant_cause(shocks, day)), mrr_history

        # Contraction: more likely when health is poor, but possible any time.
        hbar = _mean_health_before(health, idx, 60)
        hazard = contraction_daily * (1.0 + 3.2 * max(0.0, 0.6 - hbar))
        if rng.random() < hazard and current_mrr > base_mrr * 0.35:
            cut = rng.uniform(0.25, 0.55)
            current_mrr = int(current_mrr * (1.0 - cut))
            mrr_history.append((day, current_mrr))
            return Outcome("contraction", _dt(day), _dominant_cause(shocks, day)), mrr_history

        # Expansion happens too, and a model that only ever sees decline learns
        # a biased view of what normal movement looks like.
        if rng.random() < 0.00035 * (1.0 + 2.0 * max(0.0, hbar - 0.7)):
            current_mrr = int(current_mrr * rng.uniform(1.12, 1.45))
            mrr_history.append((day, current_mrr))

    return Outcome(None, None, None), mrr_history


def _dominant_cause(shocks: list[tuple[date, str]], when: date) -> str:
    recent = [k for (d, k) in shocks if 0 <= (when - d).days <= 180]
    if not recent:
        return "slow_decline"
    negative = [k for k in recent if k != "qbr_success"]
    return negative[-1] if negative else "slow_decline"


def _dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=UTC)
