"""
Refresh tokens (ADR §10): stored hashed, rotated on every use, grouped in families.

A family is every token descending from one /token code exchange. Presenting a token that was
already rotated or revoked means a copy is in someone else's hands: the whole family and the
session die, since we can't tell the thief's copy from the user's.
"""

from __future__ import annotations

import secrets
import uuid

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from sqlalchemy import select
from sqlalchemy import func

from authentint.config import settings
from authentint.audit import audit
from authentint.infra.models.audit import Sessions
from authentint.infra.models.oauth import OAuthAuthorizationCodes
from authentint.infra.models.oauth import OAuthRefreshTokens
from authentint.security.passwords import hash_token


async def issue_refresh(session: AsyncSession, origin: OAuthAuthorizationCodes | OAuthRefreshTokens) -> str:
    """
    From a code: the first token of a new family. From a refresh token (rotation): its child, same family.
    The child keeps the parent's scope even when the request narrowed it (RFC 6749 §6).
    """

    parent = origin if isinstance(origin, OAuthRefreshTokens) else None
    raw_token = secrets.token_urlsafe(32)
    session.add(OAuthRefreshTokens(
        token_hash=hash_token(raw_token),
        family_id=parent.family_id if parent else uuid.uuid4(),
        parent_hash=parent.token_hash if parent else None,
        client_id=origin.client_id,
        user_id=origin.user_id,
        session_id=origin.session_id,
        scope=origin.scope,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.refresh_token_ttl)
    ))
    await session.commit()

    return raw_token

async def find(session: AsyncSession, token: str) -> OAuthRefreshTokens | None:
    # populate_existing: rotated_at/revoked_at may have been changed by an UPDATE this session didn't see
    statement = select(OAuthRefreshTokens).where(OAuthRefreshTokens.token_hash == hash_token(token)).execution_options(populate_existing=True)

    return await session.scalar(statement)

def is_expired(row: OAuthRefreshTokens) -> bool:
    return row.expires_at <= datetime.now(timezone.utc)

async def rotate(session: AsyncSession, row: OAuthRefreshTokens) -> bool:
    """
    Marks `row` rotated, atomically: of two concurrent refreshes with the same token, only one
    UPDATE matches `rotated_at IS NULL`, the other gets False and is handled as a replay.
    """

    statement = (update(OAuthRefreshTokens)
                 .where(OAuthRefreshTokens.token_hash == row.token_hash, OAuthRefreshTokens.rotated_at.is_(None), OAuthRefreshTokens.revoked_at.is_(None))
                 .values(rotated_at=func.now()).returning(OAuthRefreshTokens.token_hash))

    return await session.scalar(statement) is not None

async def revoke_family(session: AsyncSession, family_id: UUID, reason: str) -> None:
    await session.execute(update(OAuthRefreshTokens)
                          .where(OAuthRefreshTokens.family_id == family_id, OAuthRefreshTokens.revoked_at.is_(None))
                          .values(revoked_at=func.now(), revocation_reason=reason))

async def revoke_session(session: AsyncSession, session_id: UUID, reason: str) -> None:
    """The session and every refresh token issued under it: nothing it produced outlives it."""

    await session.execute(update(Sessions).where(Sessions.id == session_id, Sessions.revoked_at.is_(None))
                          .values(revoked_at=func.now(), revocation_reason=reason))
    await session.execute(update(OAuthRefreshTokens)
                          .where(OAuthRefreshTokens.session_id == session_id, OAuthRefreshTokens.revoked_at.is_(None))
                          .values(revoked_at=func.now(), revocation_reason=reason))

async def replayed(session: AsyncSession, row: OAuthRefreshTokens) -> None:
    """ADR §10: a rotated or revoked token came back. Family + session revoked, high-severity audit, committed."""

    await revoke_session(session, row.session_id, "refresh_reuse")  # a family never spans sessions: this covers it
    await audit.emit(session, "token.refresh_reuse", actor=row.user_id, outcome="failure",
                     detail={"severity": "high", "client_id": row.client_id})
    await session.commit()
