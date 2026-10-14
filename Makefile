# Authent'INT — raccourcis. Tout passe par Docker Compose (voir README).
# Les commandes Python tournent DANS le conteneur : postgres n'est joignable que là.

EXEC := docker compose exec -T auth-server uv run --no-sync

# k6 joins Caddy's network namespace: it reaches https://auth.authentint.localhost and http://auth-server:8000
K6 := docker run --rm --user $$(id -u) --network container:$$(docker compose ps -q caddy) \
	-v $(CURDIR)/load:/load:ro -v $(CURDIR)/load/results:/results \
	-v $(CURDIR)/fixtures/ldap/users.json:/fixtures/users.json:ro grafana/k6:1.3.0

.PHONY: up down logs seed test openapi psql load load-scale3 scale3-check scale1

up:       ## build, migrate, start, wait for every healthcheck
	docker compose up -d --build --wait

down:
	docker compose down

logs:
	docker compose logs -f auth-server

seed:     ## dev only: 5 users + the portail-web client (make seed N=400: the first N fixture users)
	$(EXEC) python -m scripts.seed $(N)

test:     ## all tests, or one file: make test T=tests/integration/test_users.py
	$(EXEC) pytest $(T)

openapi:  ## regenerate the interaction-API contract (docs/generated/openapi.json)
	$(EXEC) python -m scripts.export_openapi > docs/generated/openapi.json

psql:
	docker compose exec postgres psql -U authentint_owner authentint

load:     ## k6 against the running stack (first: make seed N=400). Results: load/results/, report: docs/load-report.md
	mkdir -p load/results
	$(K6) run -e LABEL=$(or $(LABEL),run) /load/k6.js

scale3-check: ## ADR §15: 3 replicas recreated together → one active + one next key, all ready, tokens verify everywhere
	./scripts/check_scale.sh

load-scale3: ## k6 at 3 replicas, the multi-replica check, then back to 1 replica
	docker compose up -d --wait --scale auth-server=3
	-$(MAKE) load LABEL=scale3
	-./scripts/check_scale.sh
	$(MAKE) scale1

scale1:
	docker compose up -d --wait --scale auth-server=1
