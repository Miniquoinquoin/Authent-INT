"""Seed the dev database so that /authorize can work end to end.

The database starts empty after `alembic upgrade head`. With no row in `clients`,
/authorize rejects every request with `invalid_client`; with no user holding a
password, nobody can log in. This script inserts:

- a few users taken from the fake LDAP directory (fixtures/ldap/users.json),
  all active, all with the password DEV_PASSWORD (hashed with hash_password);
- the `portail-web` client (the SPA), with its redirect_uris, allowed_scopes
  and require_consent.

Idempotent: every row is an upsert, so running it twice changes nothing. It
never deletes anything. Dev only: outside DEV=true, settings.fixtures_path is
None and the script refuses to run.

    docker compose exec auth-server uv run --no-sync python -m scripts.seed
"""

import asyncio
import itertools
import sys

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from authentint.config import settings
from authentint.external.directory import JsonDirectory, role_for
from authentint.infra.database import Session
from authentint.infra.models.identity import User, UserStatus
from authentint.infra.models.oauth import OAuthClients
from authentint.security.passwords import hash_password

DEV_PASSWORD = "Authentint-dev-1!"  # DEV ONLY — shared by every seeded user
SEED_USERS = 5  # ponytail: first 5 fixtures only (1 admin, 2 agents, 2 contribuables); argon2 on all 10 006 would take minutes

CLIENTS = [{"id": "portail-web", "name": "Portail", "type": "public", "secret_hash": None,
            "redirect_uris": ["https://app.authentint.local/callback"],  # to align with the frontend router
            "post_logout_redirect_uris": ["https://app.authentint.local/"],
            "allowed_grants": ["authorization_code", "refresh_token"],
            "allowed_scopes": ["openid", "offline_access", "svc:impots.read", "svc:impots.write",
                               "svc:cadastre.read", "svc:cadastre.write", "svc:admin.users", "svc:admin.audit"],
            "require_consent": False}]


async def main():
    if not settings.fixtures_path:
        sys.exit("seed is dev only (DEV=true)")

    password_hash = await hash_password(DEV_PASSWORD)
    users = list(itertools.islice(JsonDirectory(settings.fixtures_path).list_all(), SEED_USERS))

    async with Session() as s:
        for du in users:
            values = {"numero_fiscal": du.numero_fiscal, "nom": du.nom, "prenom": du.prenom, "email": du.email,
                      "role": role_for(du.groups), "status": UserStatus.active,
                      "password_hash": password_hash, "password_changed_at": func.now()}
            await s.execute(insert(User).values(external_id=du.external_id, **values)
                            .on_conflict_do_update(index_elements=["external_id"], set_=values))
        for c in CLIENTS:
            await s.execute(insert(OAuthClients).values(**c).on_conflict_do_update(index_elements=["id"], set_=c))
        await s.commit()

    print(f"seeded {len(users)} users (password: {DEV_PASSWORD}) and {len(CLIENTS)} client(s)")
    for du in users:
        print(f"  {du.numero_fiscal}  {role_for(du.groups).value}")


if __name__ == "__main__":
    asyncio.run(main())
