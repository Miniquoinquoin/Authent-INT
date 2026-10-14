"""
Interaction API (ADR §9): the frontend drives the steps of one pending /authorize.

The `uid` is an opaque handle to server-side state: client_id, scope and redirect_uri
never travel through the browser, so they can't be tampered with. The server alone
decides the next step (`next_step`); the client is never trusted on where it stands.

B0 freezes the request/response shapes below: they are exported to
docs/generated/openapi.json, which the frontend mocks (seam S3).
`login` and `consent` belong to B1 and answer 501 until then.
"""

import secrets

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import router
from authentint.config import settings
from authentint.audit import audit
from authentint.clients import queries as clients
from authentint.domain.scopes import grant
from authentint.domain.errors import error_url
from authentint.flows import consent as consents
from authentint.flows.login import ACCOUNT_LIMIT
from authentint.flows.login import ACCOUNT_WINDOW
from authentint.flows.login import AccountLocked
from authentint.flows.login import account_bucket
from authentint.flows.login import authenticate
from authentint.infra.database import get_session
from authentint.sessions import queries as sessions
from authentint.infra.models.identity import User
from authentint.infra.models.oauth import OAuthClients
from authentint.infra.models.oauth import OAuthInteractions
from authentint.security import ratelimit
from authentint.security.identifiers import numero_fiscal_digest


TTL = timedelta(minutes=10)

LOGIN_LIMIT = 10                      # login attempts per IP...
LOGIN_WINDOW = timedelta(minutes=1)   # ...per minute: a family behind one box is fine, a script is not

Prompt = Literal["login", "consent"]  # the MFA seam (ADR §2) will add "otp"


class InteractionView(BaseModel):
    prompt: Prompt | None = Field(description="Step to display next. null: finished, follow redirect_to")
    client_name: str
    scopes: list[str]
    redirect_to: str | None = Field(None, description="Set when prompt is null: back to /authorize, which issues the code")

class LoginBody(BaseModel):
    numero_fiscal: str = Field(pattern=r"^\d{13}$")
    password: str = Field(min_length=1, max_length=1024)

class ConsentBody(BaseModel):
    approve: bool


async def create(session: AsyncSession, params, user_id: UUID | None = None) -> OAuthInteractions:
    """
    Called by /authorize (oidc/). `params` is its validated AuthorizeParams.
    No SSO session: user_id is None, the first step is login.
    A session but no consent yet: user_id is the session's user, the first step is consent.
    """

    it = OAuthInteractions(
        uid=secrets.token_urlsafe(32), client_id=params.client_id, redirect_uri=params.redirect_uri,
        scope=params.scope, state=params.state, nonce=params.nonce, code_challenge=params.code_challenge,
        code_challenge_method=params.code_challenge_method, stage="login" if user_id is None else "consent",
        user_id=user_id, expires_at=datetime.now(UTC) + TTL,
    )
    session.add(it)
    await session.commit()

    return it

async def load(session: AsyncSession, uid: str) -> OAuthInteractions:
    it = await session.scalar(select(OAuthInteractions).where(OAuthInteractions.uid == uid, OAuthInteractions.expires_at > func.now()))

    if it is None:
        raise HTTPException(404, "unknown_interaction")  # same answer for unknown and expired

    return it

def next_step(it: OAuthInteractions, client: OAuthClients, has_consent: bool) -> Prompt | None:
    if it.user_id is None:
        return "login"
    # the MFA seam (ADR §2) goes here: `if needs_otp: return "otp"`
    if client.require_consent and not has_consent:
        return "consent"
    return None

def resume_url(it: OAuthInteractions) -> str:
    """The original /authorize request, rebuilt from server-side state: the session cookie now exists, so it takes the SSO path."""

    return f"{settings.issuer}/authorize?" + urlencode({
        "response_type": "code", "client_id": it.client_id, "redirect_uri": it.redirect_uri, "scope": it.scope,
        "state": it.state, "nonce": it.nonce, "code_challenge": it.code_challenge,
        "code_challenge_method": it.code_challenge_method,
    })

async def shown_scopes(session: AsyncSession, it: OAuthInteractions, client: OAuthClients) -> list[str]:
    """
    What the user is asked to approve, and what a consent records. Once the user is known, it is
    what /authorize will GRANT (ADR §7), not what the client asked for: nobody approves a scope
    their role will never get. Before login the role is unknown: the request as is.
    """

    if it.user_id is None:
        return it.scope.split()
    user = await session.get(User, it.user_id)
    return sorted(grant(set(it.scope.split()), user.role, client))

async def view(session: AsyncSession, it: OAuthInteractions) -> InteractionView:
    client = await clients.get(session, it.client_id)
    scopes = await shown_scopes(session, it, client)
    has_consent = it.user_id is not None and await consents.covers(session, it.user_id, it.client_id, set(scopes))
    prompt = next_step(it, client, has_consent)

    return InteractionView(prompt=prompt, client_name=client.name, scopes=scopes,
                           redirect_to=resume_url(it) if prompt is None else None)


@router.get("/interaction/{uid}", response_model=InteractionView, responses={404: {"description": "Unknown or expired uid"}})
async def get_interaction(uid: str, session: AsyncSession = Depends(get_session)):
    return await view(session, await load(session, uid))

@router.post("/interaction/{uid}/login", response_model=InteractionView, status_code=200, responses={
    401: {"description": "Bad numero_fiscal or password (same answer for both)"},
    404: {"description": "Unknown or expired uid"},
    423: {"description": "Account locked"},
    429: {"description": "Rate limited"},
})
async def login(uid: str, body: LoginBody, request: Request, response: Response,
                session: AsyncSession = Depends(get_session)):
    """On success, sets the `__Host-session` cookie and answers the next step."""

    # First, before any Argon2 work: one source cannot try more than LOGIN_LIMIT times per LOGIN_WINDOW
    ip = request.client.host if request.client else "unknown"
    # ...and one account cannot be tried more than ACCOUNT_LIMIT times, from however many IPs.
    # Unknown numeros get a bucket too: the answer never tells whether the account exists
    ok = (await ratelimit.hit(session, f"login:ip:{ip}", LOGIN_LIMIT, LOGIN_WINDOW)
          and await ratelimit.hit(session, account_bucket(numero_fiscal_digest(body.numero_fiscal)), ACCOUNT_LIMIT, ACCOUNT_WINDOW))
    await session.commit()  # the counters must survive whatever happens next (429, 401, 423, 404...)
    if not ok:
        raise HTTPException(429, "too_many_attempts")

    it = await load(session, uid)
    try:
        user = await authenticate(session, body.numero_fiscal, body.password)
    except AccountLocked:
        await session.commit()  # keep the login.locked audit event
        raise HTTPException(423, "account_locked")

    if user is None:
        await session.commit()  # keep the failure count (lockout)
        raise HTTPException(401, "invalid_credentials")

    sso = await sessions.create(session, user, request)
    it.user_id = user.id
    await audit.emit(session, "login.success", actor=user.id, outcome="success", detail={}, session_id=sso.id)
    await session.commit()  # session + interaction + audit, together

    response.set_cookie("__Host-session", str(sso.id), httponly=True, secure=True, samesite="lax", path="/")

    return await view(session, it)

@router.post("/interaction/{uid}/consent", response_model=InteractionView, responses={
    400: {"description": "Not logged in yet: login comes first"},
    404: {"description": "Unknown or expired uid"},
})
async def consent(uid: str, body: ConsentBody, session: AsyncSession = Depends(get_session)):
    """approve=false ends the flow: redirect_to then carries error=access_denied."""

    it = await load(session, uid)
    if it.user_id is None:
        raise HTTPException(400, "login_required")  # the server decides the order of the steps, not the client

    client = await clients.get(session, it.client_id)
    scopes = await shown_scopes(session, it, client)

    if not body.approve:
        it.expires_at = func.now()  # the flow is over: this uid can't be replayed (DB clock, like load())
        await audit.emit(session, "consent.denied", actor=it.user_id, outcome="failure", detail={}, client_id=it.client_id)
        await session.commit()
        return InteractionView(prompt=None, client_name=client.name, scopes=scopes,
                               redirect_to=error_url(it.redirect_uri, "access_denied", it.state))

    await consents.record(session, it.user_id, it.client_id, set(scopes))
    await audit.emit(session, "consent.granted", actor=it.user_id, outcome="success",
                     detail={"scopes": scopes}, client_id=it.client_id)
    await session.commit()

    return await view(session, it)
