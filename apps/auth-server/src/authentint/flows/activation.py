"""
Account activation (ADR §9 "Cycle de vie du compte") — B1.

Users come from the directory WITHOUT a password (pending_activation). To log in the
first time, they ask for a link by e-mail (request), then choose a password (confirm).

Two rules carry the security:
- the link carries a random token, and the database only stores its HASH: a dump of
  the database gives no usable link (same idea as passwords);
- `request` answers EXACTLY the same whether the account exists or not (invariant 8),
  otherwise it becomes an oracle listing which numeros fiscaux have an account.
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
from sqlalchemy.ext.asyncio import AsyncSession

from . import router
from authentint.audit import audit
from authentint.config import settings
from authentint.external.mailer import Mailer
from authentint.external.mailer import get_mailer
from authentint.infra.database import get_session
from authentint.infra.models.identity import ActivationTokens
from authentint.infra.models.identity import UserStatus
from authentint.security import ratelimit
from authentint.security.passwords import hash_token
from authentint.users import queries as users


TTL = timedelta(minutes=30)
REQUEST_LIMIT = 5                       # activation e-mails per IP...
REQUEST_WINDOW = timedelta(minutes=15)  # ...per quarter of an hour: nobody can mail-bomb a user

ACCEPTED = {"status": "accepted"}  # the ONE answer of /request, whatever happened


class ActivationRequest(BaseModel):
    numero_fiscal: str = Field(pattern=r"^\d{13}$")


@router.post("/account/activation/request", status_code=202, tags=["account"], responses={
    429: {"description": "Rate limited"},
})
async def request_activation(body: ActivationRequest, request: Request, background: BackgroundTasks,
                             session: AsyncSession = Depends(get_session), mailer: Mailer = Depends(get_mailer)):
    """Always 202 with the same body: whether an e-mail left is never told."""

    ip = request.client.host if request.client else "unknown"
    if not await ratelimit.hit(session, f"activation:ip:{ip}", REQUEST_LIMIT, REQUEST_WINDOW):
        raise HTTPException(429, "too_many_attempts")

    user = await users.by_numero_fiscal(session, body.numero_fiscal)
    if user is None or user.status != UserStatus.pending_activation:
        await session.commit()  # the rate-limit counter
        return ACCEPTED  # unknown, or already active (they use password reset): same answer

    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)

    session.add(ActivationTokens(user_id=user.id, token_hash=token_hash,
                                 expires_at=datetime.now(UTC) + TTL, requested_ip=ip))
    await audit.emit(session, "activation.requested", actor=user.id, outcome="success", detail={})
    await session.commit()

    # Sent after the answer: a slow mail relay must not make "account exists" slower than "doesn't" (invariant 8)
    background.add_task(mailer.send, user.email, "Activation de votre compte Authent'INT",
                        f"Choisissez votre mot de passe : {settings.public_base_url}/activate?token={token}\n"
                        f"Ce lien expire dans {TTL.seconds // 60} minutes.")
    return ACCEPTED
