"""Shapes and constants for the simulated estate.

The generator plays the part of five external systems. It is deliberately
outside ``backend/pulse`` and communicates only through the on-disk feeds
described in ``specs/.../contracts/ingestion.md`` — the same interface a real
integration would use. Nothing in the application imports anything from here,
and a reviewer can check that claim with one grep.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

SOURCES = ("salesforce", "gmail", "zendesk", "product", "stripe")

SEGMENTS = ("smb", "mid", "enterprise")

INDUSTRIES = (
    "real_estate", "proptech", "mortgage", "insurance", "construction",
    "property_management", "title_escrow", "home_services",
)

REGIONS = ("us_west", "us_east", "us_central", "canada", "emea")

FEATURE_KEYS = (
    "dashboard", "reports", "campaigns", "contacts", "automations",
    "integrations", "mobile", "exports", "ai_insights", "team_sharing",
)


@dataclass(frozen=True)
class TenantSpec:
    """One customer organisation of Pulse.

    The three here are not three copies of each other. Each exists to make a
    specific claim in the specification testable with real data:

    ``northwind`` is the well-instrumented case — all five sources, three years
    of history, enterprise-weighted. It is what the system looks like when
    everything works.

    ``globex`` has **no Gmail connection at all**. Every email-derived feature
    must come out absent rather than zero for its entire estate, the model must
    handle that natively, and the coverage report must say so. This is the
    single most useful tenant in the dataset, because imputing zero here would
    read as "every customer has gone silent" and the system would mark a whole
    organisation red.

    ``initech`` onboarded seven months ago. No account in it has the history
    that the 90- and 180-day windows want, so it exercises the cold-start and
    abstain paths at tenant scale, and it is what the leave-one-tenant-out
    evaluation is for.
    """

    slug: str
    name: str
    n_accounts: int
    connected_sources: tuple[str, ...]
    history_months: int
    segment_weights: tuple[float, float, float]
    n_csms: int
    # Monthly compound growth in signups. A real SaaS has more recent customers
    # than old ones, so account age is skewed young with a long tail — which is
    # also why "three years of history" does not mean three years *per account*.
    signup_growth: float = 0.08


TENANTS: tuple[TenantSpec, ...] = (
    TenantSpec(
        slug="northwind", name="Northwind Realty Group", n_accounts=2800,
        connected_sources=SOURCES, history_months=36,
        segment_weights=(0.40, 0.42, 0.18), n_csms=24,
        signup_growth=0.10,
    ),
    TenantSpec(
        slug="globex", name="Globex Property Partners", n_accounts=1700,
        connected_sources=("salesforce", "zendesk", "product", "stripe"),
        history_months=36, segment_weights=(0.68, 0.28, 0.04), n_csms=14,
        signup_growth=0.11,
    ),
    TenantSpec(
        slug="initech", name="Initech Home Services", n_accounts=500,
        connected_sources=SOURCES, history_months=7,
        segment_weights=(0.55, 0.38, 0.07), n_csms=5,
        signup_growth=0.14,
    ),
)

# Seat counts by segment: lognormal, because account size in any real estate is
# heavy-tailed. A mean would be meaningless; the tail is where the ACV is.
SEAT_LOGNORM = {"smb": (1.7, 0.6), "mid": (3.4, 0.55), "enterprise": (5.2, 0.5)}

# Annual contract value per seat, in cents, by segment. Larger accounts pay more
# per seat here (enterprise tiers), which is the usual shape and matters because
# value-at-risk is what the ranking multiplies by.
ACV_PER_SEAT = {"smb": 18_000_00 // 12, "mid": 26_000_00 // 12, "enterprise": 41_000_00 // 12}


@dataclass
class ShockSpec:
    """A discrete event that moves an account's latent health.

    Each has a distinct observable signature, which is the point: a model that
    only saw a single aggregate "health" signal could not tell a champion
    departure from a billing problem, and the CSM's next action differs
    completely between them.
    """

    key: str
    annual_rate: float          # Poisson intensity, per account-year
    magnitude: float            # immediate change to latent health
    persistence: float          # how much it also drags the mean-reversion target
    recoverable: bool


SHOCKS: tuple[ShockSpec, ...] = (
    # The champion leaves. Usage collapses in a very specific way — one user's
    # activity goes to zero and nobody replaces them — and email threads lose
    # their most engaged participant. Classic silent-churn precursor.
    ShockSpec("champion_departure", 0.22, -0.26, 0.45, recoverable=False),
    # Our support fails them: a P1 that sits, slow first responses, a reopen.
    # This one is *our* fault, which is exactly why automatically emailing the
    # customer a cheerful check-in would be insulting.
    ShockSpec("support_failure", 0.34, -0.17, 0.35, recoverable=True),
    # They start evaluating a competitor. Shows up as a slow fade: fewer
    # sessions, narrower feature use, slower replies.
    ShockSpec("competitive_eval", 0.16, -0.13, 0.60, recoverable=True),
    # A successful QBR or a new use case lands. Health genuinely improves.
    ShockSpec("qbr_success", 0.45, +0.16, 0.40, recoverable=True),
    # A price increase at renewal. Brief, sharp, often survivable.
    ShockSpec("price_increase", 0.12, -0.11, 0.20, recoverable=True),
    # An org change on their side: new owner, new priorities, budget scrutiny.
    ShockSpec("sponsor_change", 0.18, -0.14, 0.40, recoverable=True),
)


@dataclass
class AccountSpec:
    """Everything fixed about one simulated account."""

    tenant_slug: str
    index: int
    external_ref: str
    name: str
    segment: str
    industry: str | None
    region: str | None
    seats: int
    acv_cents: int
    signup: date
    owner_ref: str
    users: list[str] = field(default_factory=list)
    champion: str = ""
    # Source-native identifiers. They are intentionally unrelated to each other,
    # because in a real estate they are minted by five different systems and the
    # join between them is a mapping table that is never complete.
    sf_ref: str = ""
    zd_ref: str = ""
    stripe_ref: str = ""
    gmail_domain: str = ""
    product_ref: str = ""


@dataclass
class Outcome:
    """What eventually happened, and when.

    ``kind`` distinguishes a full cancellation from a material contraction
    because the business cares about both and a model trained only on
    cancellations learns nothing from the downgrade that precedes half of them.
    """

    kind: str | None            # None | "churn" | "contraction"
    at: datetime | None
    cause: str | None           # which shock dominated, or "exogenous"


COMPANY_PREFIXES = (
    "Summit", "Harbor", "Cedar", "Ironwood", "Bluepeak", "Westgate", "Northstar",
    "Lakeshore", "Brightline", "Stonebridge", "Redwood", "Fairhaven", "Granite",
    "Silverline", "Meadowview", "Copperfield", "Oakmont", "Riverbend", "Kestrel",
    "Alderwood", "Pinnacle", "Hollowbrook", "Windmere", "Castlegate", "Sunvale",
)

COMPANY_SUFFIXES = (
    "Realty", "Properties", "Group", "Partners", "Advisors", "Holdings",
    "Management", "Residential", "Estates", "Capital", "Homes", "Collective",
)
