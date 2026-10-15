"""Request-scoped dependencies. Tenant identification is a header for this
deliverable's scope -- a real deployment resolves it from an authenticated
session, but every downstream path (RLS session, query) is identical either
way, which is the point: tenant isolation does not depend on how the caller
was identified.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from pulse.agent.transport import RecordingTransport, Transport
from pulse.db.session import tenant_session


def get_tenant_id(x_tenant_id: str = Header(...)) -> uuid.UUID:
    return uuid.UUID(x_tenant_id)


def get_session(tenant_id: uuid.UUID = Depends(get_tenant_id)) -> Iterator[Session]:
    with tenant_session(tenant_id) as s:
        yield s


# Production would override this with a real email-provider-backed
# Transport; this deliverable's default is the recording stub -- never a
# real network call, consistent with running fully functional with no
# external services configured (constitution Principle II's same posture,
# applied to outbound dispatch rather than drafting).
def get_transport() -> Transport:
    return RecordingTransport()
