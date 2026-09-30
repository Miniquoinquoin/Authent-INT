from sqlalchemy.ext.asyncio import AsyncSession

from authentint.infra.models.oauth import OAuthClients


async def get(session: AsyncSession, client_id: str | None) -> OAuthClients | None:
    return await session.get(OAuthClients, client_id) if client_id else None
