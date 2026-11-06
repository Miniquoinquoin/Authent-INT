"""Set up a deployment: register the portail-web client and, optionally, import directory users.

Works outside dev, unlike seed.py: it needs neither DEV=true nor /fixtures, and it holds no password.
Imported users start as pending_activation and choose their password through the activation link.

    python -m scripts.bootstrap                              # the client only
    python -m scripts.bootstrap scripts/example_users.json   # + the users of a directory file

example_users.json is AT YOUR OWN RISK: its numbers are public, one of them is an admin, and until a real
mailer exists the activation links are written to the logs. Whoever reads the logs can activate that admin.

Safe to rerun: a client that exists is left alone (an admin may have edited it), and a user that exists only
gets its directory fields refreshed, never its status or password.
"""

import asyncio
import sys

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from authentint.config import settings
from authentint.external.directory import JsonDirectory
from authentint.external.directory import UserDirectory
from authentint.external.directory import role_for
from authentint.infra.database import Session
from authentint.infra.models.identity import User
from authentint.infra.models.identity import UserStatus
from authentint.infra.models.oauth import OAuthClients
from authentint.security.identifiers import numero_fiscal_digest
from scripts.seed import CLIENTS


def portail_client() -> dict:
    """The portal's client row, on this deployment's origin instead of seed.py's *.localhost."""

    return {**CLIENTS[0],
            "redirect_uris": [f"{settings.public_base_url}/callback"],
            "post_logout_redirect_uris": [f"{settings.public_base_url}/"]}


async def register_client(session: AsyncSession) -> None:
    await session.execute(insert(OAuthClients).values(**portail_client()).on_conflict_do_nothing(index_elements=["id"]))


async def import_users(session: AsyncSession, directory: UserDirectory) -> int:
    """Copies the directory into users and returns how many it processed. status and password_hash stay out of the update."""

    count = 0
    for du in directory.list_all():
        synced = {"numero_fiscal_hmac": numero_fiscal_digest(du.numero_fiscal), "nom": du.nom, "prenom": du.prenom,
                  "email": du.email, "role": role_for(du.groups), "synced_at": func.now()}
        await session.execute(insert(User).values(external_id=du.external_id, status=UserStatus.pending_activation, **synced)
                              .on_conflict_do_update(index_elements=["external_id"], set_=synced))
        count += 1
    return count


async def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else None

    # One commit: a failure (two external_ids claiming one number, a bad file) leaves nothing half-imported
    async with Session() as session:
        await register_client(session)
        count = await import_users(session, JsonDirectory(path)) if path else 0
        await session.commit()

    print(f"client portail-web ready, {count} directory user(s) processed")


if __name__ == "__main__":
    asyncio.run(main())
