"""Account activation: `issue_activation()` and `/account/activation/confirm`.

There is deliberately no `/account/activation/request`. The login attempt is the
trigger (P§6), which removes an endpoint *and* removes an enumeration oracle —
there is no endpoint left to ask "does this account exist?".
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import security
from app.config import settings
from app.infra.db import get_db
from app.models import ActivationToken, Status, User
from app.schemas import ActivationConfirm, Failure, refuse

log = logging.getLogger(__name__)
router = APIRouter(tags=["account"])

TOKEN_FAILURE = Failure(detail="Lien d'activation invalide ou expiré.")


async def issue_activation(db: AsyncSession, user: User, ip: str | None) -> str:
    """Mint a one-shot token and store its **hash** (§6). Returns the plaintext.

    The caller mails it. Callers must schedule that send *after* the response:
    an SMTP round trip on one branch of the login flow and not the others is a
    timing oracle, which is exactly what P§7 step 4 forbids.
    """
    token, token_hash = security.new_token()
    db.add(
        ActivationToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(seconds=settings().activation_ttl_s),
            requested_ip=ip,
        )
    )
    await db.commit()
    log.info(
        "activation.issued",
        extra={"event": {"event_type": "activation.issued", "outcome": "success", "user_id": str(user.id)}},
    )
    return token


# No `status_code=204` on the decorator: the refusal branches carry a body,
# and FastAPI (rightly) forbids declaring a body-less status for a route that
# can return one. Success sets 204 explicitly instead.
@router.post("/account/activation/confirm")
async def confirm(
    body: ActivationConfirm,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Token + chosen password → the account's first password."""
    row = await db.scalar(
        select(ActivationToken).where(ActivationToken.token_hash == security.digest(body.token))
    )
    now = datetime.now(UTC)
    # Unknown, already used, and expired are one answer. Distinguishing them
    # tells an attacker which tokens exist.
    if row is None or row.consumed_at is not None or row.expires_at <= now:
        log.info(
            "activation.refused",
            extra={"event": {"event_type": "activation.refused", "outcome": "failure"}},
        )
        return refuse(TOKEN_FAILURE, status=400)

    user = await db.scalar(select(User).where(User.id == row.user_id))
    if user is None or user.status not in (Status.PENDING_ACTIVATION, Status.LOCKED):
        # A disabled account is not activatable, and an active one already has a
        # password — that is the password-reset flow, which is B1's second half.
        return refuse(TOKEN_FAILURE, status=400)

    user.password_hash = await security.hash_password(body.password)
    user.status = Status.ACTIVE
    user.password_changed_at = now
    user.updated_at = now
    user.failed_login_count = 0
    user.locked_until = None
    row.consumed_at = now
    await db.commit()

    log.info(
        "activation.confirmed",
        extra={"event": {"event_type": "activation.confirmed", "outcome": "success", "user_id": str(user.id)}},
    )
    return Response(status_code=204)
