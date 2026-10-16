# Backend image: the API, the unattended worker and the CLI share it and differ only in the command.
# UNVERIFIED: this file has not been built -- Docker is not installed on the machine it was written on.
# syntax=docker/dockerfile:1

FROM python:3.13-slim AS build
WORKDIR /src
COPY backend/pyproject.toml ./
COPY backend/pulse ./pulse
# Installed into a separate prefix so the final image carries no build cache or compiler.
RUN pip install --no-cache-dir --prefix=/install ".[llm]"

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 pulse
WORKDIR /app/backend
COPY --from=build /install /usr/local
COPY backend/alembic.ini ./
COPY backend/pulse ./pulse
COPY generator /app/generator
COPY infra/docker/entrypoint.sh /usr/local/bin/entrypoint.sh
# Data and models live in volumes mounted here, never in the image.
RUN mkdir -p /app/data /app/artifacts && chown -R pulse:pulse /app && chmod +x /usr/local/bin/entrypoint.sh
USER pulse
ENV PYTHONUNBUFFERED=1 PGTZ=UTC
EXPOSE 8000
ENTRYPOINT ["entrypoint.sh"]
CMD ["uvicorn", "pulse.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
