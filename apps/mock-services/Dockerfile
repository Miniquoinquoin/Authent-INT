# syntax=docker/dockerfile:1
#
# One image for every mock Resource Server: SERVICE_NAME, ISSUER, AUDIENCE and
# CA_BUNDLE come from the environment (docker-compose.yml, docs/architecture.md §3).

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
# Separating dependencies from project files to prevent useless Docker rebuilds
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-install-project --no-dev
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev

ENV PORT=8001
EXPOSE 8001
CMD ["sh", "-c", "exec uv run --no-sync uvicorn --factory mockservices.main:create_app --host 0.0.0.0 --port \"$PORT\""]
