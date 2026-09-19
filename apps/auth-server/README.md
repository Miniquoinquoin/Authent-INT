# auth-server

FastAPI backend of Authent'INT. Today it is a **learning-stage JWT login API**, adapted from Eric Roby's YouTube video *"JWT Authentication for React and FastAPI"*. The final OpenID Provider described in `docs/architecture.md` will replace most of it; the layout (`src/authentint/infra/`, Alembic, uvicorn in Docker) is already the target one.

## What was adapted from the video

| Video | Here | Why |
|---|---|---|
| SQLite + sync SQLAlchemy | Postgres + async SQLAlchemy 2.0 (`asyncpg`) | The stack runs Postgres in Docker; the ADR mandates async |
| `passlib` | `bcrypt` called directly | `passlib` is unmaintained and breaks with `bcrypt` ≥ 4.1 |
| `Base.metadata.create_all()` at import | in the FastAPI `lifespan` | Async engine can't run sync DDL at import; Alembic will own the schema |
| `database.py` / `models.py` at project root | `src/authentint/infra/` | Installable package, importable from Alembic and tests |
| `localhost:8000` from the SPA | `https://auth.authentint.local` via Caddy | Only Caddy publishes a port; CORS allows `PUBLIC_BASE_URL` |
| `python-jose`, `react-router-dom` | same, `react-router` | — |

## Layout

```
src/authentint/
├── main.py              FastAPI app, routes, JWT helpers
└── infra/
    ├── database.py      async engine, session factory, get_session() dependency
    └── models.py        SQLAlchemy models (User)
alembic/                 migrations — not initialised yet
scripts/seed.py          empty for now
```

## How a request flows

```
POST /register  {username, password}
  → get_user_by_username()  SELECT … WHERE username = ?   (400 if it exists)
  → create_user()           bcrypt.hashpw → INSERT → commit

POST /token  username=…&password=…   (OAuth2 password form)
  → authenticate_user()     SELECT + bcrypt.checkpw          (401 on miss)
  → create_access_token()   HS256 JWT {sub: username, exp: now+30 min}
  ← {"access_token": …, "token_type": "bearer"}

GET /verify-token/{token}
  → jwt.decode()            403 if bad signature / expired
```

**Sessions.** One `AsyncSession` per request, opened and closed by `get_session()` (`infra/database.py`) and injected with `Depends(get_session)`. Queries use `select()` + `await db.scalar(...)`; every call to an `async def` is awaited — a missing `await` returns a coroutine object, which is always truthy and silently breaks `if user:` checks.

**Passwords** are stored as bcrypt hashes. **Tokens** are symmetric HS256 with a placeholder `SECRET_KEY` in `main.py` — fine for the exercise, to be replaced by the asymmetric keystore of the real OP.

## Running

Everything runs through Docker Compose from the repo root — see the root README for the host setup (`/etc/hosts`, Caddy's CA).

```sh
docker compose up -d --build auth-server        # immutable image, uvicorn on :8000 behind Caddy
docker compose logs -f auth-server
```

Dev loop with live reload: put `COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml` in `.env` (copy `.env.example`). `docker-compose.dev.yml` bind-mounts `src/` into the container and runs uvicorn with `--reload`. Rebuild only when `uv.lock` changes.

Environment, injected by compose: `DATABASE_URL` (`postgresql+asyncpg://…@postgres/…`), `PUBLIC_BASE_URL` (the SPA origin, used for CORS), `ISSUER`, `LOG_LEVEL`.

## Try it

Swagger UI: `https://auth.authentint.local/docs`. Or from the shell:

```sh
curl -k https://auth.authentint.local/register -H 'Content-Type: application/json' \
     -d '{"username":"alice","password":"correct-horse"}'
curl -k https://auth.authentint.local/token -d 'username=alice&password=correct-horse'
```

There is no default user — the `users` table starts empty.
