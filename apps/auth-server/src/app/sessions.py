"""Session lifecycle and the cookie. Postgres is the source of truth.

Never reads Valkey. Revocation has to survive a Valkey restart, so there is no
Valkey copy of a session in this phase at all (§11b rule 1). The `sid:*` index
arrives in B9, in front of a query somebody has by then measured.
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import security
from app.config import settings
from app.models import Session, User

log = logging.getLogger(__name__)

#: What the ID token will claim at B2. Written now because a session that was
#: not recorded as MFA-authenticated cannot be backfilled into one (P§4).
ACR_MFA = "urn:authentint:acr:mfa"
AMR_PASSWORD_AND_OTP = ["pwd", "otp"]


def device_label(user_agent: str | None) -> str:
    """"Firefox / Windows", for the device list B8 will render.

    A substring sniff, not a UA parser: the label is a human hint on a
    self-service screen, and nothing branches on it.
    """
    if not user_agent:
        return "Appareil inconnu"
    browsers = [("Firefox", "Firefox"), ("Edg/", "Edge"), ("Chrome", "Chrome"), ("Safari", "Safari")]
    systems = [("Windows", "Windows"), ("Mac OS", "macOS"), ("Android", "Android"), ("iPhone", "iOS"), ("Linux", "Linux")]
    browser = next((label for token, label in browsers if token in user_agent), "Navigateur")
    system = next((label for token, label in systems if token in user_agent), "système inconnu")
    return f"{browser} / {system}"


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def create(db: AsyncSession, user: User, request: Request) -> tuple[Session, str]:
    """Open a session and return it with the plaintext cookie value.

    Only the digest is stored: the cookie is a bearer credential, and §6's rule
    about never storing a token in plaintext covers this one.
    """
    token, token_hash = security.new_session_token()
    now = datetime.now(UTC)
    session = Session(
        token_hash=token_hash,
        user_id=user.id,
        device_label=device_label(request.headers.get("user-agent")),
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip(request),
        expires_at=now + timedelta(seconds=settings().session_absolute_ttl_s),
        acr=ACR_MFA,
        amr=AMR_PASSWORD_AND_OTP,
    )
    db.add(session)
    await db.commit()
    log.info(
        "session.opened",
        extra={"event": {"event_type": "session.opened", "outcome": "success", "user_id": str(user.id), "sid": str(session.id)}},
    )
    return session, token


async def resolve(db: AsyncSession, token: str | None) -> tuple[Session, User] | None:
    """The live session behind a cookie, or None.

    This lookup becomes §8 step 6 — the SSO check — at B2, unchanged.
    """
    if not token:
        return None
    session = await db.scalar(select(Session).where(Session.token_hash == security.digest(token)))
    if session is None or session.revoked_at is not None:
        return None

    now = datetime.now(UTC)
    idle_deadline = session.last_seen_at + timedelta(seconds=settings().session_idle_ttl_s)
    if session.expires_at <= now or idle_deadline <= now:
        return None

    user = await db.scalar(select(User).where(User.id == session.user_id))
    if user is None or user.status.value in ("disabled", "locked"):
        # A session outlives an account change only until the next request.
        return None

    session.last_seen_at = now
    await db.commit()
    return session, user


async def revoke(db: AsyncSession, session: Session, reason: str) -> None:
    session.revoked_at = datetime.now(UTC)
    session.revocation_reason = reason
    await db.commit()
    log.info(
        "session.revoked",
        extra={"event": {"event_type": "session.revoked", "outcome": "success", "sid": str(session.id), "reason": reason}},
    )


def set_cookie(response: Response, token: str) -> None:
    cfg = settings()
    response.set_cookie(
        cfg.cookie_name,
        token,
        max_age=cfg.session_absolute_ttl_s,
        httponly=True,
        secure=cfg.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_cookie(response: Response) -> None:
    cfg = settings()
    response.delete_cookie(cfg.cookie_name, path="/", httponly=True, secure=cfg.cookie_secure, samesite="lax")


def read_cookie(request: Request) -> str | None:
    return request.cookies.get(settings().cookie_name)
