"""One service, one origin, for hosts that run a single web service (spec 003).

``/api/*`` is the existing application with the prefix removed (the UI already calls ``/api/...``; in the container stack
nginx strips it, here this does); every other path is the built UI, falling back to ``index.html`` so that refreshing the
browser on ``/browse`` still works. Nothing about the application's behaviour changes: sessions, CSRF header, roles and
row-level security are all the existing code.

Run it with ``uvicorn --factory pulse.api.hosted:create_app`` (the UI folder comes from ``PULSE_UI_DIR``, default ``/app/ui``).
"""

from __future__ import annotations

import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles


class _SpaFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


def build_hosted_app(api, ui_dir: Path) -> Starlette:
    return Starlette(routes=[Mount("/api", app=api), Mount("/", app=_SpaFiles(directory=str(ui_dir), html=True))])


def create_app() -> Starlette:
    from pulse.api.main import app as api
    return build_hosted_app(api, Path(os.environ.get("PULSE_UI_DIR", "/app/ui")))
