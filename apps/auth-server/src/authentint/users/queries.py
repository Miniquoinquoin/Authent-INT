from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authentint.infra.models.identity import User


async def by_numero_fiscal(session: AsyncSession, numero_fiscal: str) -> User | None:
    """
    The login identifier (ADR §7). Returns None when nobody has this number:
    the caller must then answer exactly as for a wrong password.
    """

    return await session.scalar(select(User).where(User.numero_fiscal==numero_fiscal))
