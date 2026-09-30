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
├── flows/       interaction · activation · reset (to come)
└── oidc/        discovery · jwks · authorize (WIP) · codes · token (to come)
alembic/         versioned migrations — a deliverable
scripts/seed.py  dev only: 5 directory users + the portail-web client
```

## Running

Everything runs through Docker Compose from the repo root — see the root README
for the host setup (`/etc/hosts`, Caddy's CA).

```sh
cp .env.example .env            # then fill KEY_ENCRYPTION_KEY (command in the file)
docker compose up -d --build
docker compose exec auth-server uv run --no-sync alembic upgrade head   # first run, and after each new migration
docker compose restart auth-server                                      # the lifespan needs the tables
docker compose exec auth-server uv run --no-sync python -m scripts.seed # dev only (needs docker-compose.dev.yml)
```

Migrations are not applied at boot yet: on an empty database the app exits with
`relation "signing_keys" does not exist`.

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
