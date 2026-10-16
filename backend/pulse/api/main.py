"""The FastAPI application. Tenant isolation is enforced by the database
(constitution Principle IV) -- every route goes through ``get_session``, which
opens a tenant-scoped, RLS-enforced transaction per request, with the tenant
taken from the caller's verified session and nothing they assert.
"""

from __future__ import annotations

from fastapi import FastAPI

from pulse.api.routers import (
    accounts,
    actions,
    admin,
    auth,
    feedback,
    model,
    queue,
    runs,
    suppression,
    users,
)

app = FastAPI(title="Pulse")
app.include_router(auth.router)
app.include_router(queue.router)
app.include_router(accounts.router)
app.include_router(actions.router)
app.include_router(admin.router)
app.include_router(model.router)
app.include_router(runs.router)
app.include_router(feedback.router)
app.include_router(suppression.router)
app.include_router(users.router)
