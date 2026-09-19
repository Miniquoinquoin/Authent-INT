# syntax=docker/dockerfile:1

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
# Separating dependencies from project files to prevent useless Docker rebuilds
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-install-project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "authentint.main:app", "--host", "0.0.0.0", "--port", "8000"]
