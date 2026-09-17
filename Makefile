# Phase 1 — docs/authentication-server.md §10.
.PHONY: up down migrate sync test docs fmt

SERVER := apps/auth-server
UV     := uv run --project $(SERVER)

.env:
	cp .env.example .env

up: .env                       ## bring the stack up and wait for it
	docker compose up -d --build
	docker compose ps

down:
	docker compose down

migrate: .env                  ## alembic upgrade head, from the host
	cd $(SERVER) && uv run alembic upgrade head

sync: .env                     ## fixture -> users, idempotent (§5)
	cd $(SERVER) && uv run python -m app.sync

test: .env                     ## pytest against the compose Postgres and Valkey (§9)
	cd $(SERVER) && uv run pytest -q

scale:                         ## the §9 multi-replica check
	docker compose rm -sf auth-server
	AUTH_SERVER_PORTS=8000-8002:8000 docker compose up -d --scale auth-server=3
	docker compose ps auth-server

unscale:
	docker compose rm -sf auth-server
	docker compose up -d auth-server

docs:                          ## OpenAPI document -> docs/generated (§4 deliverable)
	$(UV) python -c "import json, app.main as m; print(json.dumps(m.app.openapi(), indent=2, ensure_ascii=False))" > docs/generated/openapi.json
	@echo "wrote docs/generated/openapi.json"
