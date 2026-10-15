"""The FastAPI application. Tenant isolation is enforced by the database
(constitution Principle IV) -- every route goes through ``get_session``, which
opens a tenant-scoped, RLS-enforced transaction per request.
"""

from __future__ import annotations

from fastapi import FastAPI

from pulse.api.routers import accounts, actions, queue

app = FastAPI(title="Pulse")
app.include_router(queue.router)
app.include_router(accounts.router)
app.include_router(actions.router)
