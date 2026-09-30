from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy import func
from fastapi import Request

from authentint.infra.models.audit import Sessions


async def from_cookie(session: AsyncSession, request: Request) -> Sessions | None:
    session_id = request.cookies.get("__Host-session")

    if session_id is None:
        return None

    return await session.scalar(select(Sessions).where(Sessions.id == session_id, Sessions.revoked_at.is_(None), Sessions.expires_at > func.now()))
