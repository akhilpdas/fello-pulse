"""Start-up for a single-service host (Render, Railway): translate the platform's settings, migrate, seed an empty
database, then serve (spec 003). ``python3 -m pulse.hosted_boot`` is the container's command.

Hosting platforms hand out one database URL with one account. The application wants the ``psycopg`` driver prefix for
the owner (migrations, seed loading) and the restricted ``pulse_app`` login -- which cannot bypass row-level security --
for everything that serves a request. Same host, same database, different user.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit


def normalise_owner_url(url: str) -> str:
    for old in ("postgresql://", "postgres://"):
        if url.startswith(old):
            return "postgresql+psycopg://" + url[len(old):]
    return url


def app_url_from(owner_url: str) -> str:
    parts = urlsplit(owner_url)
    host = parts.netloc.rpartition("@")[2]
    return urlunsplit(parts._replace(netloc=f"pulse_app:pulse_app@{host}"))


def _wait_for_database(url: str, attempts: int = 60) -> None:
    import psycopg
    plain = url.replace("postgresql+psycopg://", "postgresql://")
    for n in range(attempts):
        try:
            psycopg.connect(plain, connect_timeout=5).close()
            return
        except Exception as exc:  # noqa: BLE001
            print(f"waiting for the database ({n + 1}/{attempts}): {type(exc).__name__}", flush=True)
            time.sleep(2)
    sys.exit("the database never became reachable")


def _tenant_count(url: str) -> int:
    import psycopg
    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://")) as conn:
        return conn.execute("SELECT count(*) FROM tenant").fetchone()[0]


def main() -> None:
    owner = normalise_owner_url(os.environ.get("PULSE_DATABASE_URL_OWNER") or os.environ["DATABASE_URL"])
    os.environ["PULSE_DATABASE_URL_OWNER"] = owner
    os.environ.setdefault("PULSE_DATABASE_URL_APP", app_url_from(owner))
    _wait_for_database(owner)
    subprocess.run(["alembic", "-c", "alembic.ini", "upgrade", "head"], check=True)
    seed_url = os.environ.get("PULSE_SEED_URL")
    if seed_url and _tenant_count(owner) == 0:
        print("empty database: loading the demo seed ...", flush=True)
        subprocess.run([sys.executable, "-m", "pulse.cli", "load-seed", "--url", seed_url,
                        "--artifacts", os.environ.get("PULSE_ARTIFACTS_DIR", "/app/artifacts")], check=True)
    port = os.environ.get("PORT", "8000")
    os.execvp("uvicorn", ["uvicorn", "--factory", "pulse.api.hosted:create_app", "--host", "0.0.0.0", "--port", port])


if __name__ == "__main__":
    main()
