"""
Password reset (ADR §9 "Cycle de vie du compte") — B1.

Same mechanism as activation.py (random link, stored hashed, used once, same answer
whether the account exists), for ACTIVE accounts. One thing is new: a reset is what
a user does when they think someone else knows their password, so every session
open with the old password must die with it.
"""

import secrets

from datetime import UTC
from datetime import datetime
from datetime import timedelta

from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from . import router
from authentint.audit import audit
from authentint.config import settings
from authentint.external.mailer import Mailer
from authentint.external.mailer import get_mailer
from authentint.infra.database import get_session
from authentint.infra.models.identity import PasswordResetTokens
from authentint.infra.models.identity import User
from authentint.infra.models.identity import UserStatus
from authentint.security import ratelimit
from authentint.security.passwords import NewPassword
from authentint.security.passwords import hash_password
from authentint.security.passwords import hash_token
from authentint.sessions import queries as sessions
from authentint.users import queries as users


TTL = timedelta(minutes=30)
REQUEST_LIMIT = 5
REQUEST_WINDOW = timedelta(minutes=15)

ACCEPTED = {"status": "accepted"}  # the ONE answer of /request, whatever happened


class ResetRequest(BaseModel):
    numero_fiscal: str = Field(pattern=r"^\d{13}$")

class ResetConfirm(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    password: NewPassword


@router.post("/account/password-reset/request", status_code=202, tags=["account"], responses={
    429: {"description": "Rate limited"},
})
async def request_reset(body: ResetRequest, request: Request, background: BackgroundTasks,
                        session: AsyncSession = Depends(get_session), mailer: Mailer = Depends(get_mailer)):
    """Always 202 with the same body: whether an e-mail left is never told."""

    ip = request.client.host if request.client else "unknown"
    if not await ratelimit.hit(session, f"reset:ip:{ip}", REQUEST_LIMIT, REQUEST_WINDOW):
        raise HTTPException(429, "too_many_attempts")

    user = await users.by_numero_fiscal(session, body.numero_fiscal)
    if user is None or user.status != UserStatus.active:
        await session.commit()  # the rate-limit counter
        return ACCEPTED  # unknown, not activated yet (they use activation), or locked by an admin

    token = secrets.token_urlsafe(32)
    session.add(PasswordResetTokens(user_id=user.id, token_hash=hash_token(token),
                                    expires_at=datetime.now(UTC) + TTL, requested_ip=ip))
    await audit.emit(session, "password_reset.requested", actor=user.id, outcome="success", detail={})
    await session.commit()

    background.add_task(mailer.send, user.email, "Réinitialisation de votre mot de passe Authent'INT",
                        f"Choisissez un nouveau mot de passe : {settings.public_base_url}/reset-password?token={token}\n"
                        f"Ce lien expire dans {TTL.seconds // 60} minutes. Si vous n'avez rien demandé, ignorez ce message.")
    return ACCEPTED


@router.post("/account/password-reset/confirm", tags=["account"], responses={
    400: {"description": "Unknown, expired or already used link (same answer for the three)"},
})
async def confirm_reset(body: ResetConfirm, session: AsyncSession = Depends(get_session)):
    """The link's token + the new password. Every open session of the account is closed."""

    row = await session.scalar(select(PasswordResetTokens).where(
        PasswordResetTokens.token_hash == hash_token(body.token),
        PasswordResetTokens.consumed_at.is_(None), PasswordResetTokens.expires_at > func.now()))
    if row is None:
        raise HTTPException(400, "invalid_token")
    user = await session.get(User, row.user_id)
    if user.status != UserStatus.active:
        raise HTTPException(400, "invalid_token")  # disabled by an admin meanwhile

    user.password_hash = await hash_password(body.password)
    user.password_changed_at = func.now()
    user.failed_login_count, user.locked_until = 0, None  # the owner proved it's them: lift the lockout
    await session.execute(update(PasswordResetTokens)
                          .where(PasswordResetTokens.user_id == user.id, PasswordResetTokens.consumed_at.is_(None))
                          .values(consumed_at=func.now()))

    # Whoever logged in with the old password is logged out now: every session of this user, and its refresh tokens
    await sessions.revoke_all(session, user.id, "password_reset")

    await audit.emit(session, "password_reset.confirmed", actor=user.id, outcome="success", detail={})
    await session.commit()

    return {"status": "password_changed"}
