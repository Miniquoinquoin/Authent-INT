# syntax=docker/dockerfile:1
#
# One image for every mock Resource Server: SERVICE_NAME, ISSUER, AUDIENCE and
# CA_BUNDLE come from the environment (docker-compose.yml, docs/architecture.md §3).
# Two stages: uv builds the venv, the runtime image keeps only the venv and the code, non-root.
# No dev stage: the mocks' tests run on the host (`uv run pytest`, .github/workflows/mock-services.yml).

FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
# Separating dependencies from project files to prevent useless Docker rebuilds
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-install-project --no-dev
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev


FROM python:3.13-slim AS runtime
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin mockservices
WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PORT=8001
USER 10001
EXPOSE 8001
CMD ["sh", "-c", "exec uvicorn --factory mockservices.main:create_app --host 0.0.0.0 --port \"$PORT\""]
