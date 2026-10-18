# One image, one port: the API and the built UI together, for hosts that run a single web service (Render, Railway).
# Build:  docker build -f infra/docker/hosted.Dockerfile -t pulse-hosted .
# Run:    needs DATABASE_URL (or PULSE_DATABASE_URL_OWNER), PULSE_DEMO_PASSWORD and, to fill an empty database, PULSE_SEED_URL.
# See docs/HOSTING.md. The container stack (docker-compose.yml) is unchanged and remains the local path.
# syntax=docker/dockerfile:1

FROM node:22-alpine AS ui
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS build
WORKDIR /src
COPY backend/pyproject.toml ./
COPY backend/pulse ./pulse
RUN pip install --no-cache-dir --prefix=/install ".[llm]"

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 pulse \
 && apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY --from=build /install /usr/local
COPY backend/alembic.ini ./
COPY backend/pulse ./pulse
COPY --from=ui /web/dist /app/ui
RUN mkdir -p /app/artifacts && chown -R pulse:pulse /app
USER pulse
ENV PYTHONUNBUFFERED=1 PGTZ=UTC PULSE_UI_DIR=/app/ui PULSE_ARTIFACTS_DIR=/app/artifacts
EXPOSE 8000
CMD ["python3", "-m", "pulse.hosted_boot"]
