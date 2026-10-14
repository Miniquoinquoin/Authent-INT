"""
Consent (ADR §10 step 9): the user agrees to give a client the scopes it asks for.
Stored per (user, client), so the question is asked once, not at every login,
and asked again only when the client asks for something new.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authentint.infra.models.oauth import OAuthConsents


async def covers(session: AsyncSession, user_id: UUID, client_id: str, requested: set[str]) -> bool:
    """True when this user already agreed to give this client every scope in `requested`."""

    rows = await session.scalars(select(OAuthConsents.scopes).where(
        OAuthConsents.user_id == user_id, OAuthConsents.client_id == client_id, OAuthConsents.revoked_at.is_(None)))

    granted: set[str] = set()
    for scopes in rows:  # one row per past "Accept": put all their scopes in one set
        granted |= set(scopes)

    if requested <= granted:
        return True
    return False

async def record(session: AsyncSession, user_id: UUID, client_id: str, scopes: set[str]) -> None:
    session.add(OAuthConsents(user_id=user_id, client_id=client_id, scopes=sorted(scopes)))
    await session.flush()
