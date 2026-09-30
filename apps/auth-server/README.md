# auth-server

FastAPI OpenID Provider of Authent'INT. Target design: `docs/architecture.md`.
Where the code stands today (what works, what is stubbed, what comes next):
`docs/current_architecture.md`. Build order and the *why* of each file:
`docs/learning-plan.md`.

## Layout

```
src/authentint/
├── main.py      app factory: routers, middlewares, lifespan (ensures a signing key)
├── config.py    Settings, read and validated once at boot
├── infra/       engine, session, SQLAlchemy models — nothing else
├── domain/      claims · scopes · OAuth errors — pure, no I/O
├── security/    Argon2id passwords · Postgres rate limit · Bearer verification
├── external/    UserDirectory (JSON today, LDAP later) · Mailer (console today)
├── keys/        RS256 keystore (next → active → retired) · POST /admin/keys/rotate
├── audit/       emit() · request_id middleware
├── users/ clients/ sessions/   queries.py per feature (routes to come)
├── flows/       interaction API (contract frozen, login/consent → B1) · activation · reset (B1)
├── oidc/        discovery · jwks · authorize · codes · token (B2)
└── ops/         /health/live · /health/ready
alembic/         versioned migrations — a deliverable
scripts/         seed.py (dev only) · export_openapi.py
tests/           unit (no DB) · integration · security — one rolled-back transaction per test
```

## Running

Everything runs through Docker Compose from the repo root — see the root README
for the host setup (`/etc/hosts`, Caddy's CA).

```sh
cp .env.example .env   # then fill KEY_ENCRYPTION_KEY (command in the file)
make up                # build, run the `migrate` one-shot, start, wait for healthchecks
make seed              # dev only: 5 users (password in the output) + the portail-web client
make test              # pytest inside the container, against the compose Postgres
make openapi           # after touching a route: regenerate docs/generated/openapi.json
```

Migrations run in the `migrate` service before `auth-server` starts, so a new
file in `alembic/versions/` is applied by the next `make up`.

`KEY_ENCRYPTION_KEY` encrypts the signing keys stored in Postgres. Changing it
leaves the existing keys undecryptable: reset the database
(`docker compose down -v`) rather than rotating it in dev.

Dev loop with live reload: keep `COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml`
in `.env`. `docker-compose.dev.yml` bind-mounts `src/` and `alembic/`, runs uvicorn
with `--reload`, sets `DEV=true` and mounts the fake directory. Rebuild only when
`uv.lock` changes.

## Try it

```sh
R="--resolve auth.authentint.local:443:127.0.0.1"   # unnecessary if /etc/hosts is set
curl -sk $R https://auth.authentint.local/.well-known/openid-configuration
curl -sk $R https://auth.authentint.local/.well-known/jwks.json
```
