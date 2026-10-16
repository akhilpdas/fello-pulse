#!/bin/sh
# Wait for the database, migrate if this container is the one responsible (the api), then run the command.
# Only ONE service sets MIGRATE=1, so two containers never race to migrate the same schema.
set -e
python3 - <<'PY'
import os, sys, time
import psycopg
url = os.environ["PULSE_DATABASE_URL_OWNER"].replace("postgresql+psycopg://", "postgresql://")
for attempt in range(60):
    try:
        psycopg.connect(url, connect_timeout=3).close()
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"waiting for the database ({attempt + 1}/60): {type(exc).__name__}", flush=True)
        time.sleep(2)
sys.exit("database never became reachable")
PY
if [ "${MIGRATE:-0}" = "1" ]; then
  alembic -c alembic.ini upgrade head
fi
exec "$@"
