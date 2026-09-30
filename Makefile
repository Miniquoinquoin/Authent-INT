# Authent'INT — raccourcis. Tout passe par Docker Compose (voir README).
# Les commandes Python tournent DANS le conteneur : postgres n'est joignable que là.

EXEC := docker compose exec -T auth-server uv run --no-sync

.PHONY: up down logs seed test openapi psql

up:       ## build, migrate, start, wait for every healthcheck
	docker compose up -d --build --wait

down:
	docker compose down

logs:
	docker compose logs -f auth-server

seed:     ## dev only: 5 users + the portail-web client
	$(EXEC) python -m scripts.seed

test:
	$(EXEC) pytest

openapi:  ## regenerate the interaction-API contract (docs/generated/openapi.json)
	$(EXEC) python -m scripts.export_openapi > docs/generated/openapi.json

psql:
	docker compose exec postgres psql -U authentint_app authentint
