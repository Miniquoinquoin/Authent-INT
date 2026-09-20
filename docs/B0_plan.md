# Guide : écrire le schéma ADR §8 et la migration 0001

## Context
B0 requires the DB schema to be a **frozen contract** (ADR §17: "Forme de la base → `alembic/versions/0001_*.py` (§8) → débloque B1, B4"). Right now the only model that exists is a toy `User` (`username`/`hashed_password` in `infra/models.py`) which doesn't match the real `users` table in ADR §8, and there is no migration file at all (the empty placeholder was deleted last session). This is a guide, not code written for you — it's meant to be built by hand. It explains the SQLAlchemy/Alembic vocabulary needed and the order to tackle the 11 tables in, so it's not a blank-page start.

## Part 1 — the SQLAlchemy 2.0 vocabulary you'll use

Every table becomes a class inheriting `Base` (already defined in `infra/database.py`). The existing `User` class already shows the core pattern — this extends it, it doesn't reinvent it:

```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
```

`Mapped[X]` is the Python-side type; `mapped_column(...)` is where you configure the DB-side details (type override, `nullable`, `unique`, `default`, `server_default`, `index`). When `Mapped[X]` alone is unambiguous, you can skip `mapped_column()` entirely (e.g. `Mapped[str]` maps to `String` automatically) — you only need `mapped_column()` to override or add constraints.

Column types ADR §8 needs that aren't in the current model, and what to import:

| ADR pseudo-type | SQLAlchemy import | Notes |
|---|---|---|
| `uuid pk` | `sqlalchemy.dialects.postgresql.UUID` | `mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)` — Python-side default via `uuid.uuid4`, or `server_default=text("gen_random_uuid()")` if you want Postgres to generate it (needs the `pgcrypto` extension) |
| `bigserial` (audit_events.id) | `sqlalchemy.BigInteger` | `mapped_column(BigInteger, primary_key=True)` — Postgres auto-picks an identity/serial for a PK integer column |
| `enum(a, b, c)` | `sqlalchemy.Enum` + a Python `enum.Enum` class | `mapped_column(Enum(Role, name="user_role"))` — `name=` matters: Postgres creates a real named ENUM type, and you'll see it in the migration |
| `text[]` | `sqlalchemy.dialects.postgresql.ARRAY` | `mapped_column(ARRAY(String))` |
| `jsonb` | `sqlalchemy.dialects.postgresql.JSONB` | `mapped_column(JSONB)` |
| `inet` | `sqlalchemy.dialects.postgresql.INET` | `mapped_column(INET)` |
| `timestamptz` | `sqlalchemy.DateTime(timezone=True)` | always `timezone=True` — ADR is explicit everything is `timestamptz` |
| FK (`user_id`) | `sqlalchemy.ForeignKey` | `mapped_column(ForeignKey("users.id"))` |
| `created_at`/`updated_at` | `DateTime(timezone=True)` + `server_default=func.now()` | `updated_at` also wants `onupdate=func.now()` |

One thing that's *not* a column-type problem: `numero_fiscal` is "chiffré au repos" (encrypted at rest). At the schema level it's still just a `text` column — the encryption/decryption happens in application code (B1), the same pattern as `keystore.py`'s Fernet-encrypted `private_pem`. Don't try to solve that in the migration.

## Part 2 — the 11 tables, in an order that respects foreign keys

Build models in this order (a table can only reference a table defined before it):

1. **`users`** (ADR §8 "Identité") — replace the current toy model with the real columns. `role` and `status` are the first two `Enum` columns.
2. **`clients`** — no FK dependencies. `redirect_uris`, `post_logout_redirect_uris`, `allowed_grants`, `allowed_scopes` are all `ARRAY(String)`.
3. **`activation_tokens`** / **`password_reset_tokens`** — FK to `users.id`. Same shape both times (`token_hash`, `expires_at`, `consumed_at`, `requested_ip`).
4. **`interactions`** — FK to `clients.id`, nullable FK to `users.id` (filled once the password step passes).
5. **`authorization_codes`** — FK to `clients.id`, `users.id`, `sessions.id` (so `sessions` must exist first — see #7).
6. **`refresh_tokens`** — FK to `clients.id`, `users.id`, `sessions.id`.
7. **`sessions`** — FK to `users.id`. Note this must come *before* #5/#6 in the actual file since they reference it.
8. **`consents`** — FK to `users.id`, `clients.id`.
9. **`audit_events`** — nullable FK to `users.id`. This is the one table not to rely on autogenerate for (see Part 3) — plan to hand-write its migration block directly, matching the pattern already shown in `docs/learning-plan.md` (§`alembic/`).
10. **`rate_limits`** — no FK.
11. **`signing_keys`** — no FK.

### How to split the files (concrete layout)

Turn `infra/models.py` into a package, grouped exactly the way ADR §8 already groups the tables — so reading a file matches reading the matching ADR section:

```
infra/
  database.py            # unchanged: Base, engine, Session, get_session
  models/
    __init__.py          # from authentint.infra.database import Base
                          # from . import identity, oauth, audit, keys  # noqa: F401
    identity.py           # users, activation_tokens, password_reset_tokens
    oauth.py                # clients, interactions, authorization_codes, refresh_tokens, consents
    audit.py                  # sessions, audit_events, rate_limits
    keys.py                     # signing_keys
```

Why this works without circular imports: a `ForeignKey("users.id")` is a **string** looked up against `Base.metadata` at the moment the engine/Alembic actually needs it — not a Python import of the `User` class. So `oauth.py` can declare `mapped_column(ForeignKey("users.id"))` without ever importing `identity.py`. The only thing that matters is that every module has been imported *before* something reads `Base.metadata` — which is exactly what `models/__init__.py` guarantees by importing all four submodules itself.

Because of that `__init__.py`, nothing else changes: `alembic/env.py`'s existing `from authentint.infra.models import Base` line keeps working as-is (importing a package runs its `__init__.py`, which pulls in every submodule as a side effect). Only `main.py`'s `from authentint.infra.models import User` needs to become `from authentint.infra.models.identity import User`.

If four files feels like premature structure right now, a single flat `models.py` with all 11 classes is a perfectly fine alternative to start with — it's ~150-200 lines, not unreasonable — and it can be split later along these same lines once it's annoying to scroll through. Either way, the FK-by-string / import-side-effect mechanics above are what make it safe to split later without breaking anything.

### On repeating imports across the four files

Short answer: it can't be fully avoided, and that's not actually a problem — repeating `from sqlalchemy import ...` / `from sqlalchemy.orm import Mapped, mapped_column` in every model file is normal, idiomatic Python, and it's what real SQLAlchemy codebases do. Each file importing exactly the types it uses is self-documenting (you can tell `keys.py` never needs `ARRAY` just by reading its imports) — collapsing that away would trade a little repetition for a layer of indirection that costs more than it saves at this size.

One import genuinely is shared on purpose, not by accident: `from authentint.infra.database import Base` has to appear in every model file, because it's the same `Base` object everywhere that makes `Base.metadata` a single shared registry across all four files. That's not boilerplate to eliminate — it's the mechanism that makes the split work at all (see the FK-by-string point above).

For cutting down the *type-import* repetition specifically (not `Base`), one reasonable pattern is a small `infra/models/_types.py` that re-exports the handful of Postgres-specific types reused across files:
```python
# infra/models/_types.py
from sqlalchemy import ForeignKey, DateTime, Enum, BigInteger, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB, INET
from authentint.infra.database import Base
```
then each table file does one line: `from authentint.infra.models._types import Base, Mapped, mapped_column, UUID, ForeignKey, ...` (only the names it actually uses). This is a real option, but it's an extra indirection layer that can confuse "go to definition" tooling and isn't how the SQLAlchemy docs themselves do it — reach for it only if the per-file import blocks turn out to be real friction once written, not pre-emptively. Recommendation: start with plain per-file imports.

## Part 3 — turning the models into the 0001 migration

Anatomy of an Alembic revision file (what `alembic revision` generates):
```python
revision = "0001"
down_revision = None
def upgrade() -> None: ...
def downgrade() -> None: ...
```
`upgrade()`/`downgrade()` are built from `op.*` calls — mainly `op.create_table(name, *columns, **kwargs)`, `op.create_index(...)`, `op.execute(raw_sql)` for anything Alembic has no dedicated API for.

**What autogenerate will and won't catch** (this bit us before, when `env.py` couldn't see any models — now that's fixed, autogenerate will work, but it still has blind spots):
- ✅ Tables, columns, types, FKs, simple indexes, native enums — all from the models.
- ❌ `REVOKE UPDATE, DELETE ON audit_events FROM authentint_app` (ADR §8) — has to be a manual `op.execute(...)` line added after generating.
- ❌ `postgresql_partition_by="RANGE (occurred_at)"` on `audit_events` — pass this as a kwarg to `op.create_table(...)`, but this table's migration block likely needs to be hand-written rather than trusted to autogenerate, since a partitioned table also needs at least one actual partition created (`op.execute("CREATE TABLE audit_events_default PARTITION OF audit_events DEFAULT")` or a dated partition) for inserts to succeed.
- ❌ The functional unique index on `lower(email)` — add with `op.execute("CREATE UNIQUE INDEX ... ON users (lower(email))")` or `op.create_index(..., postgresql_ops={"email": "text_pattern_ops"})`-style workarounds; raw SQL is simpler here.

**Recommended sequence:**
1. Write all 11 model classes (Part 2).
2. `uv run alembic revision --autogenerate -m "initial schema"` — this drafts most of it.
3. Open the generated file and check the diff against ADR §8 line by line: did every table appear? Are the enums named sensibly? Is anything it invented (autogenerate sometimes proposes dropping things or renames it guesses wrong) actually right?
4. Add by hand: the `REVOKE` statement, the `audit_events` partitioning + a default partition, the functional email index.
5. Re-read once more start to finish — this file is the thing three other bricks (B1, B4) will build against without re-checking the work, so it's worth it.

## Editor setup note
If Part 1's imports (`UUID`, `ARRAY`, `JSONB`, `INET`, etc.) show as unresolved in VS Code, that's Pylance not using the right interpreter, not a real problem — confirmed by running them through `uv run python -c ...` against `apps/auth-server/.venv`, where they all resolve cleanly. Fix: **Cmd+Shift+P → "Python: Select Interpreter"** → pick `apps/auth-server/.venv/bin/python`. Make sure VS Code's workspace root is `Authent-INT` (repo root) — `.vscode/settings.json`'s `${workspaceFolder}`-relative path assumes that.

## Verification
1. `docker compose up -d postgres` (or full stack), then from `apps/auth-server`: `DATABASE_URL=... uv run alembic upgrade head` — should apply cleanly with no errors.
2. `docker compose exec postgres psql -U authentint_app authentint -c '\dt'` — all 11 tables should exist; `\d audit_events` should show it's partitioned and that `authentint_app` lacks `UPDATE`/`DELETE`.
3. `uv run alembic downgrade base` then `uv run alembic upgrade head` again — proves `downgrade()` isn't a stub and the migration is reversible.
4. The learning-plan's own exercise for this module: in `psql`, open two concurrent transactions both trying to consume the same `authorization_codes` row via `UPDATE ... WHERE consumed_at IS NULL RETURNING`, confirm only one gets a row back (this only matters once B2 writes that query, but it's a good sanity check that the table shape supports it).
