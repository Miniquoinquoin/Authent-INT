from datetime import UTC
from datetime import datetime
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy import func
from sqlalchemy import update
from fastapi import Request
from uuid import UUID

from authentint.infra.models.audit import Sessions
from authentint.infra.models.identity import User
from authentint.infra.models.oauth import OAuthRefreshTokens


TTL = timedelta(hours=12)  # absolute lifetime: after that, log in again (ADR §18 q.8 may change it)


async def create(session: AsyncSession, user: User, request: Request) -> Sessions:
    """
    Opens a login session for `user` on the device that sent `request`.
    Its id becomes the __Host-session cookie and the `sid` claim of every token.
    """

    user_agent = request.headers.get("user-agent", "unknown")
    now = datetime.now(UTC)
    row = Sessions(
        user_id=user.id, user_agent=user_agent, device_label=user_agent[:64],
        ip_address=request.client.host if request.client else "0.0.0.0",
        created_at=now, last_seen_at=now, expires_at=now + TTL,
        acr="urn:authentint:acr:pwd", amr=["pwd"],  # password only; MFA will add "otp" (ADR §7)
    )

    session.add(row)
    await session.flush()
    return row


async def from_cookie(session: AsyncSession, request: Request) -> Sessions | None:
    session_id = request.cookies.get("__Host-session")

    if session_id is None:
        return None

    # Throwing away garbage cookies
    try:
        session_id = UUID(session_id)
    except ValueError:
        return None

    return await live(session, session_id)


async def live(session: AsyncSession, session_id: UUID) -> Sessions | None:
    """The session if neither revoked nor expired. Filtered in SQL: a revocation by UPDATE elsewhere is always seen."""

    return await session.scalar(select(Sessions).where(Sessions.id == session_id, Sessions.revoked_at.is_(None), Sessions.expires_at > func.now()))


async def revoke_all(session: AsyncSession, user_id: UUID, reason: str, keep: UUID | None = None) -> None:
    """
    Every open session of the user but `keep` (the device asking), with their refresh tokens:
    a password change or an admin lock must log out whoever else holds the account.
    """

    await session.execute(update(OAuthRefreshTokens)
                          .where(OAuthRefreshTokens.user_id == user_id, OAuthRefreshTokens.session_id != keep, OAuthRefreshTokens.revoked_at.is_(None))
                          .values(revoked_at=func.now(), revocation_reason=reason))
    await session.execute(update(Sessions)
                          .where(Sessions.user_id == user_id, Sessions.id != keep, Sessions.revoked_at.is_(None))
                          .values(revoked_at=func.now(), revocation_reason=reason))
