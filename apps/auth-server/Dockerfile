# syntax=docker/dockerfile:1
#
# Three stages (ADR §16 hardening):
#   build    — uv resolves the locked runtime dependencies into /app/.venv
#   dev      — build + the dev group (pytest, httpx): docker-compose.dev.yml, `make test`, CI
#   runtime  — the default target: the venv and the code only, no uv, no dev deps, non-root

FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/
# .pyc compiled at build time: the runtime user cannot (and need not) write __pycache__
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
# Separating dependencies from project files to prevent useless Docker rebuilds
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-install-project --no-dev
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev


# Stays root on purpose: docker-compose.dev.yml bind-mounts src/, alembic/, tests/ with the HOST's
# owner, and `alembic revision --autogenerate` and pytest's cache write into them. A fixed uid would
# not match the developer's (or the CI runner's) uid on Linux. Dev only: never deployed.
FROM build AS dev
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "authentint.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM python:3.13-slim AS runtime
# A fixed, unprivileged uid: no shell login, no home, owns nothing it runs (code stays root-owned, read-only to it)
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin authentint
WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1
USER 10001
EXPOSE 8000
# One uvicorn process per container: scale with replicas (--scale, Kubernetes), not --workers (ops/metrics.py)
CMD ["uvicorn", "authentint.main:app", "--host", "0.0.0.0", "--port", "8000"]
