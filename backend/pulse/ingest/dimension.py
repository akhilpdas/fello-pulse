"""Maintaining the current-state ``account`` row from the event log.

Everything here is *current* state, used for display, for the queue row a CSM
reads, and for labelling. It is deliberately not what the feature layer reads
for point-in-time attributes.

That distinction is the whole reason this module is separate and documented. A
feature that read ``account.acv_cents`` would be reading today's contract value
while claiming to describe a decision taken last March — the kind of leakage
that produces an excellent backtest and a disappointing production system, and
that nothing in the pipeline would flag. As-of attributes come from the
``crm.account_updated`` event stream, filtered on ``received_at``, in
``features/compute.py``.

The churn and contraction columns written here are the label's raw material.
They are listed in ``features/denylist.py`` as unreadable from feature code, and
``tests/leakage/test_denylist_unreachable.py`` enforces that.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

# A contraction counted as loss. Per-tenant configurable because it is exactly
# the parameter a real customer argues about (clarifications A1).
DEFAULT_CONTRACTION = 0.25


def refresh_accounts(session: Session, tenant_id: uuid.UUID) -> dict:
    """Fold the CRM and billing streams into the account dimension."""
    crm = session.execute(
        text(
            """
            WITH latest AS (
              SELECT DISTINCT ON (account_id) account_id, payload, occurred_at
              FROM source_event
              WHERE event_type = 'crm.account_updated' AND account_id IS NOT NULL
              ORDER BY account_id, received_at DESC, id DESC
            ), first_seen AS (
              SELECT account_id, min(occurred_at) AS signup
              FROM source_event
              WHERE event_type = 'crm.account_updated' AND account_id IS NOT NULL
              GROUP BY account_id
            )
            UPDATE account a SET
              name          = COALESCE(l.payload->>'name', a.name),
              segment       = l.payload->>'segment',
              industry      = l.payload->>'industry',
              region        = l.payload->>'region',
              seats         = NULLIF(l.payload->>'seats','')::int,
              acv_cents     = NULLIF(l.payload->>'acv_cents','')::bigint,
              renewal_date  = NULLIF(l.payload->>'renewal_date','')::date,
              signup_date   = f.signup::date,
              -- Latest CRM state wins, including 'no contact': a person removed in the CRM must not
              -- linger here as an address we keep writing to. Never a placeholder (FR-015).
              contact_name  = NULLIF(l.payload->'primary_contact'->>'name', ''),
              contact_email = lower(NULLIF(l.payload->'primary_contact'->>'email', ''))
            FROM latest l JOIN first_seen f ON f.account_id = l.account_id
            WHERE a.id = l.account_id
            """
        )
    )

    # Owner. Resolved through the deterministic CSM email rather than a
    # source-identifier column on app_user, so the CRM's naming scheme does not
    # leak into our schema.
    session.execute(
        text(
            """
            WITH latest AS (
              SELECT DISTINCT ON (account_id) account_id,
                     COALESCE(payload->>'to_owner_ref', payload->>'owner_ref') AS owner_ref
              FROM source_event
              WHERE event_type IN ('crm.account_updated','crm.owner_changed')
                AND account_id IS NOT NULL
              ORDER BY account_id, received_at DESC, id DESC
            )
            UPDATE account a SET owner_user_id = u.id
            FROM latest l
            JOIN tenant t ON t.id = :t
            JOIN app_user u
              ON u.email = 'csm' || split_part(l.owner_ref, '-', 3)
                 || '@' || t.slug || '.example.com'
            WHERE a.id = l.account_id AND l.owner_ref IS NOT NULL
            """
        ),
        {"t": tenant_id},
    )

    mrr = session.execute(
        text(
            """
            WITH latest AS (
              SELECT DISTINCT ON (account_id) account_id,
                     NULLIF(payload->>'mrr_cents','')::bigint AS mrr
              FROM source_event
              WHERE event_type = 'billing.subscription_updated' AND account_id IS NOT NULL
              ORDER BY account_id, received_at DESC, id DESC
            )
            UPDATE account a SET mrr_cents = l.mrr
            FROM latest l WHERE a.id = l.account_id AND l.mrr IS NOT NULL
            """
        )
    )

    churned = session.execute(
        text(
            """
            WITH cancels AS (
              SELECT account_id, min(occurred_at) AS at
              FROM source_event
              WHERE event_type = 'billing.subscription_deleted' AND account_id IS NOT NULL
              GROUP BY account_id
            )
            UPDATE account a
               SET lifecycle_state = 'churned', churned_at = c.at, churn_kind = 'churn'
            FROM cancels c
            WHERE a.id = c.account_id AND a.lifecycle_state <> 'churned'
            """
        )
    )

    # A material contraction counts as loss even when the logo is retained. Half
    # of full churns are preceded by one, and a model trained only on
    # cancellations never sees that.
    contracted = session.execute(
        text(
            """
            WITH drops AS (
              SELECT account_id, min(occurred_at) AS at
              FROM source_event
              WHERE event_type = 'billing.subscription_updated'
                AND account_id IS NOT NULL
                AND NULLIF(payload->>'previous_mrr_cents','')::bigint > 0
                AND NULLIF(payload->>'mrr_cents','')::bigint
                    <= NULLIF(payload->>'previous_mrr_cents','')::bigint * (1 - :thr)
              GROUP BY account_id
            )
            UPDATE account a
               SET lifecycle_state = 'contracted', churned_at = d.at,
                   churn_kind = 'contraction'
            FROM drops d
            WHERE a.id = d.account_id AND a.lifecycle_state = 'active'
            """
        ),
        {"thr": DEFAULT_CONTRACTION},
    )

    return {
        "crm_updated": crm.rowcount,
        "mrr_updated": mrr.rowcount,
        "churned": churned.rowcount,
        "contracted": contracted.rowcount,
    }
